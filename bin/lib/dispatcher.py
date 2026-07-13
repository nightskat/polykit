from __future__ import annotations
import os
import sys
import shutil
import tempfile
import subprocess
import json
import urllib.request
import urllib.error
from pathlib import Path
from lib.states import classify, VendorState
from lib.vendors import detect, REGISTRY
from lib.quota_error import is_quota_error
from lib.dispatch_core import (
    DispatchError,
    DispatchResult,
    validate_timeout,
    validate_sandbox,
    build_codex_cmd,
    build_claude_cmd,
    build_grok_cmd,
    gemini_agy_tier,
)


def _classify_completed(vendor: str, model: str, res) -> DispatchResult:
    """M2: map kết quả subprocess → DispatchResult. returncode!=0 kèm dấu hiệu
    quota (402/insufficient credit/exhausted) → skipped/quota_capped, KHÔNG crash,
    KHÔNG coi là lỗi generic. Dùng chung cho codex/claude/grok."""
    stdout = res.stdout or ""
    if res.returncode == 0:
        return DispatchResult(status="ok", vendor=vendor, model=model,
                              summary=f"{vendor} completed successfully",
                              stdout=stdout, exit_code=0)
    stderr = res.stderr or ""
    warnings = stderr.splitlines()[:20]
    if is_quota_error(stderr, res.returncode):
        return DispatchResult(status="skipped", vendor=vendor, model=model,
                              summary=f"{vendor} quota-capped (402/exhausted)",
                              warnings=warnings, stdout=stdout,
                              exit_code=res.returncode, reason="quota_capped")
    return DispatchResult(status="error", vendor=vendor, model=model,
                          summary=f"{vendor} failed with exit code {res.returncode}",
                          warnings=warnings, stdout=stdout, exit_code=res.returncode)

def run_vendor(
    vendor: str,
    prompt: str,
    model: str = "auto",
    timeout: int = 120,
    fmt: str = "text",
    workdir: str | None = None,
    sandbox: str = "read-only",
    runner=subprocess.run,
    detector=detect,
) -> DispatchResult:
    # 1. Chạy guards
    try:
        validated_timeout = validate_timeout(timeout)
        validated_sandbox = validate_sandbox(sandbox)

        # Depth guard — non-int hoặc âm KHÔNG được bypass (Codex #1, #2).
        raw_depth = os.environ.get("XCLI_DISPATCH_DEPTH", "0")
        try:
            depth = int(raw_depth)
        except (ValueError, TypeError):
            raise DispatchError(f"XCLI_DISPATCH_DEPTH không phải số nguyên: {raw_depth!r}")
        if depth < 0:
            depth = 0  # clamp: âm không được lách qua ngưỡng >= 3
        if depth >= 3:
            raise DispatchError(f"depth {depth} >= 3, possible loop")
            
        # Prompt empty guard
        if not prompt or not prompt.strip():
            raise DispatchError("Empty prompt. Pipe content via stdin.")
            
    except DispatchError as e:
        return DispatchResult(
            status="blocked",
            vendor=vendor,
            model=model,
            summary=f"dispatch blocked: {str(e)}",
            warnings=[],
            reason="guard_violation"
        )

    # 2. Probe detector
    # EXCEPTION: gemini có nhiều lane không phụ thuộc chỉ 1 binary
    if vendor != "gemini":
        if vendor not in REGISTRY:
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=model,
                summary=f"unknown vendor: {vendor}",
                warnings=[],
                reason="unknown_vendor"
            )
        probe = detector(REGISTRY[vendor])
        state = classify(probe)
        if state != VendorState.READY:
            return DispatchResult(
                status="skipped",
                vendor=vendor,
                model=model,
                summary=f"vendor {vendor} skipped: {state.value}",
                warnings=[],
                reason=state.value,
            )

    # 3. env con
    env = os.environ.copy()
    env["XCLI_DISPATCH_DEPTH"] = str(depth + 1)

    # 4. Dispatch theo vendor
    try:
        if vendor == "codex":
            cmd = build_codex_cmd(model, validated_sandbox, workdir, fmt)
            res = runner(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=validated_timeout,
                env=env,
            )
            return _classify_completed(vendor, model, res)

        elif vendor == "claude":
            cmd = build_claude_cmd(model, prompt)
            res = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=validated_timeout,
                env=env,
            )
            if res.returncode != 0:
                stderr_lines = res.stderr.splitlines() if res.stderr else []
                warnings = stderr_lines[:20]
                return DispatchResult(
                    status="error",
                    vendor=vendor,
                    model=model,
                    summary=f"claude failed with exit code {res.returncode}",
                    warnings=warnings,
                    stdout=res.stdout or "",
                    exit_code=res.returncode,
                )
            return DispatchResult(
                status="ok",
                vendor=vendor,
                model=model,
                summary="claude completed successfully",
                warnings=[],
                stdout=res.stdout or "",
                exit_code=0,
            )

        elif vendor == "grok":
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_prompt:
                temp_prompt.write(prompt)
                temp_prompt_path = temp_prompt.name
            
            try:
                cmd = build_grok_cmd(model, validated_sandbox, workdir, fmt, temp_prompt_path)
                res = runner(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=validated_timeout,
                    env=env,
                )
                # M2: 402/insufficient-credit → quota_capped (không crash).
                return _classify_completed(vendor, model, res)
            finally:
                if os.path.exists(temp_prompt_path):
                    os.unlink(temp_prompt_path)

        elif vendor == "gemini":
            return _dispatch_gemini(prompt, model, validated_timeout, runner, env)

        elif vendor == "openrouter":
            from lib.openrouter import or_dispatch
            r = or_dispatch(prompt, model=model, timeout=validated_timeout)
            if r.ok:
                return DispatchResult(status="ok", vendor=vendor, model=model,
                                      summary="openrouter completed successfully",
                                      stdout=r.text, exit_code=0)
            if r.quota_capped:
                return DispatchResult(status="skipped", vendor=vendor, model=model,
                                      summary="openrouter quota-capped (402/429)",
                                      warnings=[r.error or ""], exit_code=r.http_code or 1,
                                      reason="quota_capped")
            return DispatchResult(status="error", vendor=vendor, model=model,
                                  summary=f"openrouter failed: {r.error}",
                                  warnings=[r.error or ""], exit_code=r.http_code or 1)

        else:
            return DispatchResult(
                status="blocked",
                vendor=vendor,
                model=model,
                summary=f"unknown vendor: {vendor}",
                warnings=[],
                reason="unknown_vendor"
            )

    except subprocess.TimeoutExpired as e:
        return DispatchResult(
            status="timeout",
            vendor=vendor,
            model=model,
            summary=f"{vendor} dispatch exceeded {validated_timeout}s",
            warnings=[],
            reason="timeout",
        )
    except Exception as e:
        return DispatchResult(
            status="error",
            vendor=vendor,
            model=model,
            summary=f"dispatch execution error: {str(e)}",
            warnings=[str(e)],
            reason="exec_error",
        )

def _dispatch_gemini(
    prompt: str,
    model: str,
    timeout: int,
    runner,
    env: dict,
) -> DispatchResult:
    # Strip 1 ký tự @ đầu prompt
    if prompt.startswith("@"):
        prompt = prompt[1:]

    warnings = []

    # --- Lane 1: agy ---
    agy_bin = shutil.which("agy.sh")
    if not agy_bin:
        home_agy = Path.home() / "scripts/agy.sh"
        if home_agy.is_file() and os.access(home_agy, os.X_OK):
            agy_bin = str(home_agy)

    is_agy_model = (
        model == "auto"
        or model.startswith("gemini-3.5-flash")
        or model.startswith("gemini-3.1-pro")
    )

    if is_agy_model and (agy_bin or shutil.which("agy")):
        tier = gemini_agy_tier(model)
        try:
            if agy_bin:
                cmd = [agy_bin, "-t", tier, prompt]
            else:
                cmd = ["agy", "--print", prompt]
                
            res = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if res.returncode == 0 and res.stdout and res.stdout.strip():
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 1 (agy)",
                    warnings=[],
                    stdout=res.stdout,
                    exit_code=0,
                )
            else:
                reason = "exit code nonzero" if res.returncode != 0 else "empty output"
                warnings.append(f"lane 1 failed: agy execution failed ({reason})")
        except subprocess.TimeoutExpired:
            warnings.append("lane 1 failed: agy timed out")
        except Exception as e:
            warnings.append(f"lane 1 failed: {type(e).__name__}: {str(e)}")
    else:
        if not is_agy_model:
            warnings.append("lane 1 failed: model not supported by agy")
        else:
            warnings.append("lane 1 failed: agy.sh and agy unavailable")

    # --- Lane 2: gemini CLI ---
    gemini_bin = shutil.which("gemini")
    if gemini_bin:
        cli_model = "gemini-2.5-flash" if model == "auto" else model
        try:
            res = runner(
                [gemini_bin, "-m", cli_model, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if res.returncode == 0 and res.stdout and res.stdout.strip():
                deg_warnings = warnings.copy()
                deg_warnings.append("degraded: succeeded on lane 2")
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 2 (cli)",
                    warnings=deg_warnings,
                    stdout=res.stdout,
                    exit_code=0,
                )
            else:
                reason = "exit code nonzero" if res.returncode != 0 else "empty output"
                warnings.append(f"lane 2 failed: gemini-cli execution failed ({reason})")
        except subprocess.TimeoutExpired:
            warnings.append("lane 2 failed: gemini-cli timed out")
        except Exception as e:
            warnings.append(f"lane 2 failed: {type(e).__name__}: {str(e)}")
    else:
        warnings.append("lane 2 failed: gemini-cli unavailable")

    # --- Lane 3: API ---
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        key_file = Path.home() / ".gemini/api_key"
        if key_file.is_file():
            try:
                api_key = key_file.read_text().strip()
            except Exception as e:
                warnings.append(f"lane 3 failed: cannot read api_key file ({type(e).__name__}: {str(e)})")

    if api_key:
        api_model = "gemini-2.5-flash" if model == "auto" else model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{api_model}:generateContent"
        
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                
            parts = resp_data["candidates"][0]["content"]["parts"]
            stdout = "".join(p.get("text", "") for p in parts)
            
            if stdout and stdout.strip():
                deg_warnings = warnings.copy()
                deg_warnings.append("degraded: succeeded on lane 3")
                return DispatchResult(
                    status="ok",
                    vendor="gemini",
                    model=model,
                    summary="gemini succeeded on lane 3 (api)",
                    warnings=deg_warnings,
                    stdout=stdout,
                    exit_code=0,
                )
            else:
                warnings.append("lane 3 failed: empty text response")
        except urllib.error.HTTPError as e:
            try:
                err_detail = e.read().decode("utf-8")
            except Exception:
                err_detail = str(e)
            warnings.append(f"lane 3 failed: HTTP error {e.code} ({err_detail})")
        except urllib.error.URLError as e:
            warnings.append(f"lane 3 failed: URL error ({str(e.reason)})")
        except Exception as e:
            warnings.append(f"lane 3 failed: API call failed ({type(e).__name__}: {str(e)})")
    else:
        warnings.append("lane 3 failed: API key unavailable")

    # All failed
    return DispatchResult(
        status="error",
        vendor="gemini",
        model=model,
        summary="all gemini lanes failed",
        warnings=warnings,
        stdout="",
        exit_code=1,
    )
