#!/usr/bin/env python3
from __future__ import annotations
import sys
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

# Add the directory containing this script to sys.path to resolve 'lib'
sys.path.insert(0, str(Path(__file__).parent))

from lib.dispatcher import run_vendor
from lib.dispatch_core import DispatchResult
from lib.vendor_config import (
    load_vendor_config,
    vendor_names,
    default_model,
    vendor_traps,
    vendor_verify_cmd,
    vendor_zero_quota_cmds,
    vendor_auth_hint,
)


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


def _chan_som(args, resolved_model: str, summary: str, warning_lines: list[str]) -> None:
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
            reason="guard_violation",
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
    parser.add_argument("model", nargs="?", default="auto", help="Model slug to use (default: auto)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds (default: 120, max: 600)")
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

    # Fix: Add REGISTRY vendors not in JSON (like openrouter)
    from lib.vendors import REGISTRY
    for k in REGISTRY:
        if k not in names:
            names.append(k)

    args = parser.parse_args()

    # --doctor mode
    if args.doctor:
        ma = _run_doctor(args.vendor)
        if args.result_json:
            _doctor_ra_json(args.vendor, ma)
        sys.exit(ma)

    # Resolve model auto → default_model từ vendors.json
    # 🔴 dsh đặc biệt: JSON ghi default=flash nhưng flash trả rỗng trên task nhiều bước.
    # Override cứng auto → pro ở CLI, khớp với DSH_DEFAULT_MODEL trong dispatcher.
    resolved_model = args.model
    if args.model == "auto":
        if args.vendor == "dsh":
            from lib.dispatch_core import DSH_DEFAULT_MODEL
            resolved_model = DSH_DEFAULT_MODEL
        else:
            dm = default_model(args.vendor, cfg)
            if dm:
                resolved_model = dm

    # Validate model
    if resolved_model != "auto":
        vendor_data = cfg.get("vendors", {}).get(args.vendor, {})
        valid_models = vendor_data.get("models")
        if valid_models is None:
            if not args.allow_unknown_model:
                sys.stderr.write(f"[polykit] warning: model list for vendor '{args.vendor}' is unknown, cannot validate '{resolved_model}'\n")
        elif isinstance(valid_models, list):
            if resolved_model not in valid_models:
                if not args.allow_unknown_model:
                    _chan_som(
                        args, resolved_model,
                        summary=f"dispatch blocked: model '{resolved_model}' not in vendor '{args.vendor}' valid models.",
                        warning_lines=[
                            f"[polykit] error: model '{resolved_model}' not in vendor '{args.vendor}' valid models.",
                            f"Valid models: {', '.join(valid_models)}",
                            "Use --allow-unknown-model to bypass.",
                        ],
                    )

    # --dump-config: in cấu hình đã resolve, thoát 0 token
    if args.dump_config:
        info = {
            "vendor": args.vendor,
            "requested_model": args.model,
            "resolved_model": resolved_model,
            "default_model": default_model(args.vendor, cfg),
            "traps_count": len(vendor_traps(args.vendor, cfg)),
        }
        print(json.dumps(info, indent=2))
        sys.exit(0)

    # In traps ra stderr (trước khi dispatch)
    if not args.no_traps:
        traps = vendor_traps(args.vendor, cfg)
        if traps:
            sys.stderr.write(f"[polykit] ⚠ traps for {args.vendor}:\n")
            for i, trap in enumerate(traps, 1):
                sys.stderr.write(f"  {i}. {trap}\n")

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

    # Dispatch task
    result = run_vendor(
        vendor=args.vendor,
        prompt=prompt,
        model=resolved_model,
        timeout=args.timeout,
        fmt=args.format,
        workdir=args.workdir,
        sandbox=args.sandbox,
        stream=args.stream_diagnose
    )

    # M2 evidence log — best-effort, chỉ ở CLI boundary (không ghi khi test gọi lib).
    try:
        from lib.evidence import append_evidence, make_record
        from datetime import datetime, timezone
        append_evidence(make_record(
            result.vendor, result.model, result.status,
            datetime.now(timezone.utc).isoformat(), reason=result.reason,
            served_model=result.served_model,
        ))
    except Exception:
        pass

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
