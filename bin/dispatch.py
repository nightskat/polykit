#!/usr/bin/env python3
from __future__ import annotations
import sys
import time
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

# Add the directory containing this script to sys.path to resolve 'lib'
sys.path.insert(0, str(Path(__file__).parent))

from lib.dispatcher import run_vendor, resolve_dispatch_target
from lib.dispatch_core import DispatchResult, DispatchError
from lib.vendor_config import (
    load_vendor_config,
    vendor_names,
    default_model,
    vendor_traps,
    vendor_verify_cmd,
    vendor_zero_quota_cmds,
    vendor_auth_hint,
    vendor_provider,
    default_timeout,
)
from lib.model_policy import ModelPolicyViolation, SelectionSource


def _run_doctor(vendor_name: str) -> int:
    """--doctor <vendor>: chạy verify_cmd, in trạng thái + model đang chạy.
    Ưu tiên zero_quota_cmds trước."""
    cfg = load_vendor_config()
    vcmd = vendor_verify_cmd(vendor_name, cfg)
    zq = vendor_zero_quota_cmds(vendor_name, cfg)
    hint = vendor_auth_hint(vendor_name, cfg)

    if not vcmd and not zq:
        sys.stderr.write(f"[polykit] vendor '{vendor_name}' không có verify_cmd/zero_quota_cmds\n")
        return 1

    executed_cmds = set()

    # Chạy verify_cmd
    if vcmd:
        executed_cmds.add(vcmd)
        sys.stderr.write(f"[polykit] doctor: running `{vcmd}` ...\n")
        try:
            res = subprocess.run(
                vcmd, shell=True,
                capture_output=True, text=True, timeout=30,
            )
            sys.stdout.write(res.stdout)
            if res.stderr:
                sys.stderr.write(res.stderr)
            if res.returncode != 0:
                sys.stderr.write(f"[polykit] verify_cmd exited {res.returncode}\n")
                if hint:
                    sys.stderr.write(f"[polykit] auth hint: {hint}\n")
                return res.returncode
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"[polykit] verify_cmd timed out (30s)\n")
            return 124
        except Exception as e:
            sys.stderr.write(f"[polykit] verify_cmd error: {e}\n")
            return 1

    # Chạy zero_quota_cmds nếu có
    for zqc in zq[:2]:  # chạy tối đa 2 lệnh
        if zqc in executed_cmds:
            continue
        executed_cmds.add(zqc)
        sys.stderr.write(f"[polykit] doctor: running zero-quota `{zqc}` ...\n")
        try:
            res = subprocess.run(
                zqc, shell=True,
                capture_output=True, text=True, timeout=15,
            )
            sys.stdout.write(res.stdout)
            if res.stderr:
                sys.stderr.write(res.stderr)
            if res.returncode != 0:
                sys.stderr.write(f"[polykit] zero-quota cmd exited {res.returncode}\n")
                return res.returncode
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"[polykit] zero-quota cmd timed out (15s)\n")
            return 124
        except Exception as e:
            sys.stderr.write(f"[polykit] zero-quota cmd error: {e}\n")
            return 1

    sys.stderr.write(f"[polykit] doctor: {vendor_name} OK\n")
    return 0


class _ParserRaJson(argparse.ArgumentParser):
    """BUG-8 (phần Codex review chỉ ra): lỗi CỜ (vendor sai, option lạ, thiếu arg)
    do argparse xử lý TRƯỚC khi code mình chạy — nó in usage ra stderr rồi exit 2
    với stdout rỗng, kể cả khi người gọi đã xin --result-json.

    Không đọc được `args` ở thời điểm này (chưa parse xong) nên soi thẳng sys.argv.
    """

    def error(self, message):
        if "--result-json" in sys.argv:
            print(json.dumps(DispatchResult(
                status="blocked", vendor="?", model="?",
                summary=f"dispatch blocked: sai tham số dòng lệnh: {message}",
                warnings=[f"[polykit] {message}", self.format_usage().strip()],
                stdout="", exit_code=2, reason="guard_violation",
            ).to_dict(), indent=2))
        sys.stderr.write(f"[polykit] error: {message}\n")
        sys.stderr.write(self.format_usage())
        sys.exit(2)


def _doctor_ra_json(vendor: str, ma: int) -> None:
    """--doctor cũng phải tôn trọng --result-json (Codex review): trước đây nhánh
    này thoát với stdout 0 byte, đúng cái mà BUG-8 đang sửa."""
    print(json.dumps(DispatchResult(
        status="ok" if ma == 0 else "error",
        vendor=vendor, model="-",
        summary=f"doctor {vendor}: {'đạt' if ma == 0 else 'không đạt'}",
        warnings=["[polykit] chi tiết doctor đã in ra stderr."],
        stdout="", exit_code=ma,
        reason=None if ma == 0 else "doctor_failed",
    ).to_dict(), indent=2))


def _chan_som(args, resolved_model: str, summary: str, warning_lines: list[str], reason: str = "guard_violation") -> None:
    """Chặn SỚM trước khi gọi vendor (model sai, --prompt-file lỗi/rỗng).

    BUG-8: --result-json hứa stdout là JSON, nên nhánh chặn cũng phải in
    DispatchResult(status=blocked) ra stdout — nếu không stdout rỗng 0 byte và
    caller json.loads(stdout) nổ JSONDecodeError. Nội dung lỗi giữ NGUYÊN trong
    warnings (không rút gọn). Không có cờ --result-json → y như cũ: lỗi ra stderr,
    exit 2. Vẫn exit 2 (khác 1 của lỗi vendor) để script phân biệt bằng mã thoát.
    """
    for line in warning_lines:
        sys.stderr.write(line + "\n")
    if args.result_json:
        result = DispatchResult(
            status="blocked",
            vendor=args.vendor,
            model=resolved_model,
            summary=summary,
            warnings=list(warning_lines),
            stdout="",
            exit_code=2,
            reason=reason,
            served_model=None,
        )
        print(json.dumps(result.to_dict(), indent=2))
    sys.exit(2)


def main():
    cfg = load_vendor_config()
    names = vendor_names(cfg)

    # allow_abbrev=False: argparse mặc định CHO PHÉP rút gọn tiền tố, nên từ lúc
    # thêm `--prompt-file` (19/08) thì `--prompt "văn bản"` lặng lẽ biến thành
    # `--prompt-file "văn bản"` → coi câu chữ là ĐƯỜNG DẪN. Lệnh cũ đang chạy tốt
    # bỗng gãy, mà thông báo lại nói về file — sai chỗ để đi tìm (BUG-12, 20/08).
    parser = _ParserRaJson(description="Multi-vendor CLI dispatch wrapper", allow_abbrev=False)
    parser.add_argument("vendor", choices=names, help="Vendor to dispatch to")
    parser.add_argument("model", nargs="?", default=None, help="Model slug to use (default: auto)")
    parser.add_argument("--model", dest="model_flag", default=None, help="Model slug alias")
    parser.add_argument("--profile", dest="profile", default=None, help="Vendor profile configuration")
    parser.add_argument("--provider", dest="provider", default=None, help="Explicit provider (e.g. opencode-go)")
    parser.add_argument("--file", "-f", dest="files", action="append", default=[],
                        help="Attachment file for vision (repeatable: -f a.png -f b.png)")
    parser.add_argument("--synthetic-vision", action="store_true",
                        help="Explicitly declare synthetic vision attachments")
    parser.add_argument("--data-class", dest="data_class", default=None,
                        help="Khai báo loại dữ liệu cho lane Go unsandboxed. Chỉ chấp nhận "
                             "'code-nopii' (việc code/dữ liệu không PII). Thiếu cờ ⇒ "
                             "opencode/hermes vẫn bị chặn sandbox_unsupported.")
    parser.add_argument("--allow-sensitive-vision", action="store_true",
                        help="Opt-in flag for sensitive vision input")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout in seconds (max: 600). Bỏ trống = default_timeout của vendor trong vendors.json, không có thì 120 (BUG-18)")
    parser.add_argument("--prompt", dest="prompt_text", default=None,
                        help="Prompt truyền thẳng bằng chữ. Prompt dài/nhiều dòng/có dấu thì dùng --prompt-file.")
    parser.add_argument("--prompt-file", dest="prompt_file", default=None,
                        help="Đọc prompt từ file thay vì stdin (dùng cho prompt dài / nhiều dòng / tiếng Việt)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")
    parser.add_argument("--cd", dest="workdir", default=None, help="Working directory (codex/grok)")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only", help="Sandbox mode (default: read-only)")
    parser.add_argument("--result-json", action="store_true", help="Output the full DispatchResult as JSON instead of raw stdout")
    parser.add_argument("--doctor", action="store_true", help="Run verify_cmd for the vendor, print status")
    parser.add_argument("--no-traps", action="store_true", help="Suppress trap warnings on stderr")
    parser.add_argument("--dump-config", action="store_true", help="Print resolved model+vendor config and exit (0 token)")
    parser.add_argument("--allow-unknown-model", action="store_true", help="Allow models not listed in JSON")
    parser.add_argument("--stream-diagnose", action="store_true",
                        help="Chạy vendor ở chế độ stream để khi timeout còn đọc được vendor đã đi tới đâu (BUG-6). "
                             "codex/grok/agy/gemini có stream; dsh/claude KHÔNG — sẽ cảnh báo rõ rồi chạy bình thường.")
    from lib.dispatch_core import EFFORT_HOP_LE
    parser.add_argument("--effort", choices=EFFORT_HOP_LE,
                        default=None, help="Reasoning effort (codex/openrouter)")

    # Fix: Add REGISTRY vendors not in JSON (like openrouter)
    from lib.vendors import REGISTRY
    for k in REGISTRY:
        if k not in names:
            names.append(k)

    args = parser.parse_args()

    # Model positional (tương thích cũ) vs --model alias: xung đột thì CHẶN,
    # không im lặng chọn một bên.
    if args.model is not None and args.model_flag is not None:
        if args.model != args.model_flag:
            _chan_som(
                args,
                resolved_model=args.model,
                summary="dispatch blocked: conflicting positional model and --model flag",
                warning_lines=[
                    f"[polykit] error: positional model '{args.model}' conflicts with --model '{args.model_flag}'"
                ],
                reason="guard_violation",
            )
        raw_model = args.model_flag
    elif args.model_flag is not None:
        raw_model = args.model_flag
    elif args.model is not None:
        raw_model = args.model
    else:
        raw_model = "auto"

    # Nguồn GỐC của lựa chọn model. Chỉ `auto` + không profile mới là AUTO;
    # giá trị này đi thẳng vào policy và KHÔNG bị nâng thành explicit sau resolve.
    requested_source = (
        SelectionSource.AUTO
        if (raw_model == "auto" and args.profile is None)
        else SelectionSource.EXPLICIT
    )

    # Cổng Vision CLI: attachments real/unknown blocked TRƯỚC prompt-file read/
    # attachment stat/probe. Cờ --synthetic-vision chỉ mở cổng vision.py cho dữ
    # liệu tổng hợp; sensitive vẫn cần confirmation từng lượt (chưa có transport
    # sandbox ⇒ blocked honest).
    if args.files:
        if not args.synthetic_vision:
            _chan_som(
                args,
                resolved_model=raw_model or "auto",
                summary="dispatch blocked: attachments real/unknown blocked (sensitive vision unsupported without trusted UI confirmation)",
                warning_lines=[
                    "[polykit] error: sensitive or unknown attachments blocked before prompt-file read/attachment stat/probe.",
                    "Sensitive vision requires single-turn trusted UI confirmation (currently unsupported without transport sandbox).",
                    "Declare --synthetic-vision for synthetic test inputs.",
                ],
                reason="vision_blocked",
            )

    # BUG-18: không truyền --timeout → dùng trần RIÊNG của vendor
    if args.timeout is None:
        args.timeout = default_timeout(args.vendor, cfg)

    # Provider: config/resolver quyết; CLI chỉ truyền Ý ĐỊNH nếu người dùng nêu.
    provider_intent = args.provider
    if not provider_intent:
        provider_intent = vendor_provider(args.vendor, cfg)
        if not provider_intent and args.vendor == "openrouter":
            # OpenRouter không có entry trong vendors.json (REGISTRY-only).
            # Với --doctor vendor-only (raw_model auto), không gán provider=openrouter
            # để không bị chặn bởi router unresolved destination (doctor không dispatch prompt).
            if not (args.doctor and raw_model == "auto"):
                provider_intent = "openrouter"

    # Resolver CHUNG với library — cùng một quyết định, không whitelist riêng.
    resolved_model: str = raw_model or "auto"
    resolved_provider = provider_intent
    resolved_effort: str | None = args.effort
    resolved_source = requested_source
    res_warnings: list[str] = []

    try:
        target = resolve_dispatch_target(
            vendor=args.vendor,
            model=raw_model,
            provider=provider_intent,
            effort=args.effort,
            profile=args.profile,
            source=requested_source,
            allow_unknown=args.allow_unknown_model,
            cfg=cfg,
        )
    except (ModelPolicyViolation, DispatchError) as e:
        r_reason = getattr(e, "reason", None) or "policy_violation"
        _chan_som(
            args,
            resolved_model=raw_model or "auto",
            summary=f"dispatch blocked: {e}",
            warning_lines=[
                f"[polykit] error: {e}",
                f"[polykit] reason={r_reason}; requested={raw_model!r} "
                f"source={requested_source.value} — blocked trước probe/spawn/network.",
            ],
            reason=r_reason,
        )
    else:
        resolved_model = target.model
        resolved_provider = target.provider or provider_intent
        resolved_effort = target.effort
        resolved_source = target.source
        res_warnings.extend(w for w in target.warnings if w)

    # Advisory (không chặn): chưa biết danh sách model của vendor thì nói rõ là
    # không validate được slug — giữ hành vi cũ, không tự nhận là đã kiểm.
    vendor_models = (cfg.get("vendors", {}).get(args.vendor) or {}).get("models")
    if resolved_model != "auto" and vendor_models is None and not args.allow_unknown_model:
        advisory = (
            f"[polykit] warning: model list for vendor '{args.vendor}' is unknown, "
            f"cannot validate '{resolved_model}'"
        )
        sys.stderr.write(advisory + "\n")
        res_warnings.append(advisory)

    # --doctor mode: dời sau model/source/provider/vision gate nhưng vẫn trước đọc prompt-file/stdin.
    # Valid doctor vendor-only giữ contract không cần prompt; banned model hoặc
    # sensitive attachments đã bị chặn ở các cổng phía trên trước _run_doctor.
    if args.doctor:
        ma = _run_doctor(args.vendor)
        if args.result_json:
            _doctor_ra_json(args.vendor, ma)
        sys.exit(ma)

    # --dump-config: in cấu hình đã resolve, thoát 0 token
    if args.dump_config:
        info = {
            "vendor": args.vendor,
            "requested_model": raw_model,
            "resolved_model": resolved_model,
            "default_model": default_model(args.vendor, cfg),
            "traps_count": len(vendor_traps(args.vendor, cfg)),
            "source": resolved_source,
        }
        if resolved_provider:
            info["provider"] = resolved_provider
        if resolved_effort:
            info["effort"] = resolved_effort
        if args.profile:
            info["profile"] = args.profile
        if res_warnings:
            info["warnings"] = list(res_warnings)
        print(json.dumps(info, indent=2))
        sys.exit(0)

    # In traps ra stderr (trước khi dispatch)
    if not args.no_traps:
        traps = vendor_traps(args.vendor, cfg)
        if traps:
            sys.stderr.write(f"[polykit] ⚠ traps for {args.vendor}:\n")
            for i, trap in enumerate(traps, 1):
                sys.stderr.write(f"  {i}. {trap}\n")

    # Vendor thực sự nhận effort: codex (model_reasoning_effort), openrouter
    # (reasoning.effort), opencode/hermes (variant của Go profile).
    if args.effort and args.vendor not in ("codex", "openrouter", "opencode", "hermes"):
        sys.stderr.write(
            f"[polykit] warning: vendor '{args.vendor}' không nhận cờ --effort, "
            "cờ này chỉ đi vào policy/resolver, không tới vendor.\n"
        )

    # Prompt: từ --prompt-file nếu có, không thì stdin.
    # stdin không dùng được cho prompt dài — quoting, xuống dòng và dấu tiếng Việt
    # đều vỡ ở tầng shell trước khi tới đây (BUG-2, ghi nhận 18/08/2026).
    if args.prompt_text is not None and args.prompt_file:
        _chan_som(args, resolved_model,
                  summary="dispatch blocked: --prompt và --prompt-file loại trừ nhau",
                  warning_lines=["ERROR: dispatch blocked: chọn MỘT trong --prompt hoặc --prompt-file, không dùng cả hai."])
    if args.prompt_text is not None:
        prompt = args.prompt_text
        if not prompt.strip():
            _chan_som(args, resolved_model,
                      summary="dispatch blocked: --prompt rỗng",
                      warning_lines=["ERROR: dispatch blocked: --prompt rỗng."])
    elif args.prompt_file:
        try:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        except OSError as e:
            _chan_som(
                args, resolved_model,
                summary=f"dispatch blocked: không đọc được --prompt-file: {e}",
                warning_lines=[f"ERROR: dispatch blocked: không đọc được --prompt-file: {e}"],
            )
        if not prompt.strip():
            _chan_som(
                args, resolved_model,
                summary=f"dispatch blocked: --prompt-file rỗng: {args.prompt_file}",
                warning_lines=[f"ERROR: dispatch blocked: --prompt-file rỗng: {args.prompt_file}"],
            )
    else:
        prompt = sys.stdin.read()

    # M2 evidence log — best-effort, chỉ ở CLI boundary (không ghi khi test gọi lib).
    def _ghi_evidence(vendor, model, status, reason, served_model, t0):
        try:
            from lib.evidence import append_evidence, make_record
            from datetime import datetime, timezone
            append_evidence(make_record(
                vendor, model, status,
                datetime.now(timezone.utc).isoformat(), reason=reason,
                served_model=served_model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            ))
        except Exception:
            pass

    # Dispatch task
    _t0 = time.monotonic()
    try:
        result = run_vendor(
            vendor=args.vendor,
            prompt=prompt,
            model=resolved_model,
            timeout=args.timeout,
            fmt=args.format,
            workdir=args.workdir,
            sandbox=args.sandbox,
            stream=args.stream_diagnose,
            effort=resolved_effort,
            provider=resolved_provider,
            profile=args.profile,
            source=resolved_source,
            attachments=args.files if args.files else None,
            synthetic_vision=args.synthetic_vision,
            allow_sensitive_vision=args.allow_sensitive_vision,
            allow_unknown=args.allow_unknown_model,
            data_class=args.data_class,
        )
    except Exception as e:
        # BUG-18 (Codex review): lỗi bất ngờ vẫn phải để lại dấu vết + thời gian đã chạy.
        _ghi_evidence(args.vendor, resolved_model, "error", f"exception: {type(e).__name__}: {e}", None, _t0)
        raise

    for w in reversed(res_warnings):
        if w not in result.warnings:
            result.warnings.insert(0, w)

    _ghi_evidence(result.vendor, result.model, result.status, result.reason, result.served_model, _t0)

    # Model thật khác model đã gọi (router OR, lane agy, gemini auto) → báo ở stderr.
    # KHÔNG in ra stdout: stdout phải sạch để pipe sang lệnh khác.
    if result.served_model and result.served_model != resolved_model:
        sys.stderr.write(f"[polykit] served: {result.served_model}\n")

    if args.stream_diagnose:
        # Nhắc người dùng ở stderr (stdout phải sạch để pipe) — chi tiết nằm trong
        # result.warnings (xem qua --result-json).
        sys.stderr.write("[polykit] chế độ chẩn đoán stream đang bật — xem warnings qua --result-json để biết chi tiết.\n")

    if args.result_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.status == "ok":
            sys.stdout.write(result.stdout)
            # Ensure trailing newline if not present
            if result.stdout and not result.stdout.endswith('\n'):
                sys.stdout.write('\n')
        else:
            # Print failure details to stderr
            sys.stderr.write(f"ERROR: {result.summary}\n")
            if result.warnings:
                filtered_warnings = [w for w in result.warnings if "không nhận cờ model" not in w]
                if filtered_warnings:
                    sys.stderr.write("Warnings:\n")
                    for warning in filtered_warnings:
                        sys.stderr.write(f"  - {warning}\n")

    sys.exit(0 if result.status == "ok" else 1)

if __name__ == "__main__":
    main()
