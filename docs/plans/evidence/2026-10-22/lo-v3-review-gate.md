Grok-4.7 adversarial review vòng3, phần gate. CHỈ đọc source NHÚNG dưới đây, KHÔNG tools/agent/file reads. Trả tối đa3 findings thực có severity path:line, reproduction ngắn + fix, ≤25 dòng. Nếu không tìm thấy nói không thấy trong phạm vi này. Ưu tiên bypass/fail-open/auth false-ready/scorer false-correct. Không phân tích lan man, trả kết quả ngay. Context: chỉ synthetic checked-in pinned hashes, real vision cấm; doctor evidence Go TTL1h; benchmark images và PDF tách scope. 947 tests pass nhưng không coi là proof.

FILE bin/lib/vision.py
375: # ---------------------------------------------------------------------------
376: 
377: def check_no_symlinks(path: Path, root: Path) -> None:
378:     """Ensure neither path nor any ancestor up to and including root is a symlink."""
379:     # Check root itself
380:     if os.path.islink(root) or root.is_symlink():
381:         raise VisionSecurityError(f"Symlink detected in root ancestor: {root}")
382: 
383:     # Check path and all ancestors up to root without dereferencing
384:     curr = path
385:     while True:
386:         if os.path.islink(curr) or curr.is_symlink():
387:             raise VisionSecurityError(f"Symlink detected in path or ancestor: {curr}")
388:         if curr == root or curr == curr.parent:
389:             break
390:         curr = curr.parent
391: 
392: 
393: def validate_synthetic_gate(
394:     files: Sequence[str | Path],
395:     max_bytes: int = DEFAULT_MAX_FILE_BYTES,
396: ) -> list[VisionAttachment]:
397:     """Strict security and authenticity gate for synthetic vision attachments:
398:     - Fixed bench/vision/synthetic/ under REAL_REPO_ROOT (immune to fake --cd/cwd).
399:     - Manifest schema_version=1, generator=bench/vision/generate.py.
400:     - Manifest entries match pinned trusted hashes registry.
401:     - Manifest and all ancestor directories must NOT be symlinks.
402:     - Attachment files must reside inside bench/vision/synthetic/.
403:     - Attachment files and all their ancestor directories must NOT be symlinks.
404:     - No path traversal, no outside repo, no malformed, duplicate, or missing files.
405:     - Requested filename MUST appear in the manifest (manifest là danh sách đóng:
406:       file có trong registry nhưng không được generator khai báo vẫn bị chặn).
407:     - Exact SHA-256 match against manifest, trusted registry, and file on disk.
408:     - Magic bytes and file size match expected.
409: 
410:     Không có tham số ``repo_root``: cổng luôn đọc constant module
411:     ``REAL_REPO_ROOT`` (monkeypatch được trong test, sản phẩm thì không).
412:     """
413:     if not files:
414:         raise VisionFormatError("No attachment files provided for vision")
415: 
416:     root = REAL_REPO_ROOT
417:     trusted_reg = TRUSTED_SYNTHETIC_REGISTRY
418:     synth_dir = root / "bench" / "vision" / "synthetic"
419:     manifest_path = synth_dir / "manifest.json"
420: 
421:     # 1. Symlink checks on directory hierarchy and manifest
422:     check_no_symlinks(synth_dir, root)
423:     check_no_symlinks(manifest_path, root)
424: 
425:     # 2. Check manifest existence & regular file
426:     if not manifest_path.exists() or not manifest_path.is_file():
427:         raise VisionBlockedError(f"Synthetic manifest not found: {manifest_path}")
428: 
429:     # 3. Parse manifest
430:     try:
431:         with open(manifest_path, "r", encoding="utf-8") as f:
432:             manifest = json.load(f)
433:     except Exception as e:
434:         raise VisionBlockedError(f"Malformed synthetic manifest JSON: {e}") from e
435: 
436:     if not isinstance(manifest, dict):
437:         raise VisionBlockedError("Manifest root must be a JSON object")
438: 
439:     # ``type(...) is int`` (không dùng ==) để loại schema_version=true (bool),
440:     # vì True == 1 trong Python và sẽ lọt cổng nếu chỉ so sánh giá trị.
441:     schema_version = manifest.get("schema_version")
442:     if type(schema_version) is not int or schema_version != EXPECTED_MANIFEST_SCHEMA_VERSION:
443:         raise VisionBlockedError(
444:             f"Invalid manifest schema_version: {manifest.get('schema_version')!r}"
445:         )
446: 
447:     if manifest.get("generator") != EXPECTED_MANIFEST_GENERATOR:
448:         raise VisionBlockedError(
449:             f"Invalid manifest generator: {manifest.get('generator')!r}"
450:         )
451: 
452:     manifest_files = manifest.get("files")
453:     if not isinstance(manifest_files, list) or not manifest_files:
454:         raise VisionBlockedError("Manifest files must be a non-empty list")
455: 
456:     # 4. Verify manifest against trusted generator registry (pinned artifact)
457:     seen_manifest_files: set[str] = set()
458:     manifest_map: dict[str, dict[str, Any]] = {}
459: 
460:     for entry in manifest_files:
461:         if not isinstance(entry, dict):
462:             raise VisionBlockedError("Manifest file entry must be a dictionary")
463: 
464:         fname = entry.get("path")
465:         if not isinstance(fname, str) or not fname:
466:             raise VisionBlockedError("Manifest file missing path string")
467:         # Manifest là danh sách đóng trong MỘT thư mục: chỉ nhận tên file trần,
468:         # không separator, không '.', không '..', không đường dẫn tuyệt đối.
469:         if fname in (".", "..") or "/" in fname or "\\" in fname or Path(fname).name != fname:
470:             raise VisionBlockedError(
471:                 f"Manifest file path must be a plain filename: {fname!r}"
472:             )
473:         if fname in seen_manifest_files:
474:             raise VisionBlockedError(f"Duplicate file in manifest: {fname}")
475:         seen_manifest_files.add(fname)
476: 
477:         if fname not in trusted_reg:
478:             raise VisionBlockedError(
479:                 f"Manifest file {fname} is not in trusted generator registry"
480:             )
481: 
482:         record = trusted_reg[fname]
483:         if not isinstance(record, dict):
484:             raise VisionBlockedError(f"Trusted registry entry for {fname} is malformed")
485: 
486:         sha = entry.get("sha256")
487:         if not isinstance(sha, str) or not _SHA256_HEX_RE.match(sha.lower()):
488:             raise VisionBlockedError(f"Manifest file {fname} missing/invalid sha256")
489: 
490:         expected_sha = str(record.get("sha256", "")).lower()
491:         if not _SHA256_HEX_RE.match(expected_sha):
492:             raise VisionBlockedError(f"Trusted registry sha256 for {fname} is malformed")
493:         if sha.lower() != expected_sha:
494:             raise VisionBlockedError(
495:                 f"Manifest sha256 mismatch for {fname} against trusted generator registry"
496:             )
497: 
498:         # bytes phải là int thật (bool bị loại vì True == 1) và khớp registry.
499:         expected_bytes = record.get("bytes")
500:         if type(expected_bytes) is not int or expected_bytes <= 0:
501:             raise VisionBlockedError(f"Trusted registry bytes for {fname} is malformed")
502:         entry_bytes = entry.get("bytes")
503:         if type(entry_bytes) is not int or entry_bytes != expected_bytes:
504:             raise VisionBlockedError(
505:                 f"Manifest byte size mismatch for {fname} against trusted generator registry"
506:             )
507: 
508:         # format (nếu khai) phải khớp registry; rel_path (nếu khai) phải đúng cây.
509:         declared_format = entry.get("format")
510:         expected_format = record.get("format")
511:         if declared_format is not None:
512:             if (
513:                 not isinstance(declared_format, str)
514:                 or not isinstance(expected_format, str)
515:                 or declared_format.upper() != expected_format.upper()
516:             ):
517:                 raise VisionBlockedError(f"Manifest format mismatch for {fname}")
518: 
519:         declared_rel = entry.get("rel_path")
520:         expected_rel = record.get("rel_path")
521:         if declared_rel is not None and declared_rel != expected_rel:
522:             raise VisionBlockedError(f"Manifest rel_path mismatch for {fname}")
523: 
524:         manifest_map[fname] = entry
525: 
526:     # 5. Validate caller attachments
527:     validated: list[VisionAttachment] = []
528:     seen_attachments: set[str] = set()
529: 
530:     for item in files:
531:         if not item:
532:             raise VisionFormatError("Empty file path provided")
533:         p = Path(item)
534: 
535:         # Path traversal check
536:         if ".." in p.parts:
537:             raise VisionSecurityError(f"Path traversal detected in attachment: {item}")
538: 
539:         # Resolve target path relative to synth_dir
540:         if p.is_absolute():
541:             target_path = p
542:         elif len(p.parts) == 1:
543:             target_path = synth_dir / p.name
544:         else:
545:             # e.g. bench/vision/synthetic/page_01.png
546:             target_path = root / p
547: 
548:         # Check outside synthetic dir
549:         try:
550:             rel = target_path.resolve(strict=False).relative_to(synth_dir.resolve(strict=False))
551:             if len(rel.parts) != 1:
552:                 raise VisionSecurityError(
553:                     f"Attachment {item} must be directly inside {synth_dir}"
554:                 )
555:         except (ValueError, RuntimeError):
556:             raise VisionSecurityError(
557:                 f"Attachment {item} is outside fixed synthetic directory: {synth_dir}"
558:             )
559: 
560:         filename = target_path.name
561:         if filename in seen_attachments:
562:             raise VisionBlockedError(f"Duplicate attachment provided: {filename}")
563:         seen_attachments.add(filename)
564: 
565:         # Check symlink on file and all ancestors up to root
566:         check_no_symlinks(target_path, root)
567: 
568:         # Check file exists and is regular file
569:         if not target_path.exists():
570:             raise VisionFormatError(f"Synthetic file not found: {target_path}")
571:         if not target_path.is_file():
572:             raise VisionFormatError(f"Not a regular file: {target_path}")
573: 
574:         # Kiểm tra kích thước trước khi tra registry: file rỗng/quá trần trong
575:         # synthetic dir luôn bị chặn, không cần khai báo trong manifest.
576:         actual_size = target_path.stat().st_size
577:         if actual_size == 0:
578:             raise VisionFormatError(f"Synthetic file is empty: {filename}")
579:         if actual_size > max_bytes:
580:             raise VisionQuotaError(
581:                 f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
582:             )
583: 
584:         if filename not in trusted_reg:
585:             raise VisionBlockedError(
586:                 f"File {filename} is not in trusted synthetic generator registry"
587:             )
588: 
589:         # Manifest là danh sách ĐÓNG: file có trong registry nhưng generator
590:         # không khai báo trong manifest thì không được coi là synthetic hợp lệ.
591:         if filename not in manifest_map:
592:             raise VisionBlockedError(
593:                 f"Requested file {filename} is not declared in the synthetic manifest"
594:             )
595:         manifest_sha = str(manifest_map[filename].get("sha256", "")).lower()
596:         if manifest_sha != trusted_reg[filename]["sha256"].lower():
597:             raise VisionBlockedError(
598:                 f"Manifest sha256 mismatch for {filename} against trusted generator registry"
599:             )
600: 
601:         actual_size = target_path.stat().st_size
602:         if actual_size == 0:
603:             raise VisionFormatError(f"Synthetic file is empty: {filename}")
604:         if actual_size > max_bytes:
605:             raise VisionQuotaError(
606:                 f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
607:             )
608: 
609:         expected_size = trusted_reg[filename].get("bytes")
610:         if expected_size is not None and actual_size != expected_size:
611:             raise VisionBlockedError(
612:                 f"File size mismatch for {filename}: expected {expected_size}, got {actual_size}"
613:             )
614: 
615:         # SHA-256 calculation
616:         h = hashlib.sha256()
617:         with open(target_path, "rb") as fh:
618:             while chunk := fh.read(65536):
619:                 h.update(chunk)
620:         actual_sha = h.hexdigest().lower()
621:         expected_sha = trusted_reg[filename]["sha256"].lower()
622: 
623:         if actual_sha != expected_sha:
624:             raise VisionBlockedError(
625:                 f"File content modified/tampered for {filename}: sha256 mismatch"
626:             )
627: 
628:         # MIME signature via magic bytes
629:         with open(target_path, "rb") as fh:
630:             header = fh.read(32)
631:         mime = detect_mime_from_magic_bytes(header)
632:         if not mime:
633:             raise VisionFormatError(f"Invalid magic bytes signature for {filename}")
634: 
635:         # Định dạng registry phải khớp MIME thật (không tin suffix/manifest).
636:         registry_format = str(trusted_reg[filename].get("format", "")).upper()
637:         expected_mime = _FORMAT_TO_MIME.get(registry_format)
638:         if expected_mime is None or expected_mime != mime:
639:             raise VisionFormatError(
640:                 f"Magic bytes for {filename} do not match trusted registry format"
641:             )
642: 
643:         validated.append(VisionAttachment(
644:             path=target_path,
645:             mime_type=mime,
646:             size_bytes=actual_size,
647:             is_synthetic=True,
648:         ))
649: 
650:     return validated
651: 
652: 
653: def check_vision_gate(
654:     files: Sequence[str | Path],
655:     model: str,
656:     provider: str = "",
657:     adapter: str = "",
658:     is_synthetic: bool = False,
659:     allow_sensitive: bool = False,
660:     confirmation: Any = None,
661:     is_retry: bool = False,
662:     is_failover: bool = False,
663:     workspace_root: str | Path | None = None,
664:     max_bytes: int = DEFAULT_MAX_FILE_BYTES,
665: ) -> list[VisionAttachment]:
666:     """Pure gate check before ANY file I/O, subprocess, or network call.
667: 
668:     GATE CHECK ORDER:
669:     1. Sensitive / synthetic gate:
670:        - Dữ liệu thật / sensitive flags luôn bị chặn fail-closed kể cả no files.
671:        - Chỉ synthetic explicit mới được đi tiếp.
672:     2. Adapter verification check:
673:        - Adapter rỗng ("" / None / whitespace) bị chặn lập tức.
674:        - Chỉ chấp nhận adapter nằm trong frozen VERIFIED_VISION_ADAPTERS registry (opencode).
675:     3. Capabilities metadata check (theo model cụ thể).
676:     4. Kiểm tra file sau gate (synthetic generator-backed):
677:        - Manifest schema_version=1, generator bench/vision/generate.py.
678:        - Exact SHA-256 match với pinned trusted registry.
679:        - Không symlink bất kỳ ancestor nào, không traversal/outside.
680:     5. Kiểm tra tính tương thích giữa model capabilities và MIME đính kèm.
681:     """
682:     # Cờ sensitive hoặc confirmation luôn bị chặn dứt khoát
683:     if allow_sensitive:
684:         raise VisionBlockedError(
685:             "--allow-sensitive-vision is blocked fail-closed; sensitive vision unsupported."
686:         )
687:     if confirmation is not None:
688:         raise VisionBlockedError(
689:             "Sensitive vision confirmation is blocked; trusted UI unsupported."
690:         )
691: 
692:     if not files:
693:         raise VisionFormatError("No attachment files provided for vision")
694: 
695:     # -----------------------------------------------------------------------
696:     # 1. CỔNG SENSITIVE / SYNTHETIC GATE (TRƯỚC MỌI FILE I/O)
697:     # -----------------------------------------------------------------------
698:     if not is_synthetic:
699:         raise VisionBlockedError(
700:             "Sensitive or undeclared synthetic vision data is blocked by default. "
701:             "Sensitive vision is currently unsupported pending trusted UI confirmation."
702:         )
703: 
704:     # -----------------------------------------------------------------------
705:     # 2. ADAPTER CHECK (TRƯỚC MỌI FILE I/O)
706:     # -----------------------------------------------------------------------
707:     verify_adapter(adapter)
708: 
709:     # -----------------------------------------------------------------------
710:     # 3. CAPABILITIES CHECK

FILE bin/lib/dispatch_core.py
510: def _build_opencode_argv(
511:     model: str,
512:     prompt: str,
513:     effort: str | None = None,
514:     attachments: list[str] | None = None,
515:     source: str = "explicit",
516:     data_class: str | None = None,
517:     synthetic_vision: bool = False,
518:     fmt: str = "text",
519:     workdir: str | None = None,
520: ) -> list[str]:
521:     """Helper nội bộ xây dựng danh sách argv cho opencode run.
522: 
523:     KHÔNG gọi shell. Giữ prompt nguyên vẹn vị trí cuối (positional).
524:     -f dùng cho danh sách attachment (synthetic validation lô vision sau).
525:     `--` đứng ngay trước prompt để `-f` (array) không nuốt prompt thành file.
526:     fmt="json" ⇒ `--format json` (opencode phát raw JSON event stream, giữ được
527:     event tool_use để phát hiện nhiễm bẩn); fmt="text" giữ hành vi cũ.
528:     Dùng selector chuẩn hoá từ policy/resolver thay vì chuỗi thô.
529:     Lane unsandboxed chỉ mở khi caller khai báo data_class='code-nopii' và
530:     cổng dữ liệu (PII + attachment/vision) qua. Không có tham số bool override.
531:     """
532:     selector = _enforce_builder_policy(
533:         vendor="opencode",
534:         model=model,
535:         effort=effort,
536:         source=source,
537:     )
538: 
539:     try:
540:         evaluate_go_data_gate(
541:             data_class=data_class,
542:             prompt=prompt,
543:             attachments=attachments,
544:             synthetic_vision=synthetic_vision,
545:             vendor="opencode",
546:             model=selector.model,
547:             workdir=workdir,
548:         )
549:     except GoDataGateBlocked as e:
550:         raise DispatchError(
551:             str(e),
552:             reason=e.reason,
553:             model=selector.model,
554:             provider=selector.provider or GO_PROVIDER,
555:         ) from e
556: 
557:     # Xử lý attachment qua prepare_vision_input: DeepSeek tách trang PDF, GLM giữ PDF trực tiếp
558:     final_attachment_paths: list[str] = []
559:     if attachments:
560:         try:
561:             from lib.vision import prepare_vision_input, VisionError
562:         except ImportError:
563:             from bin.lib.vision import prepare_vision_input, VisionError
564:         try:
565:             prepared = prepare_vision_input(
566:                 files=attachments,
567:                 model=selector.model,
568:                 provider=selector.provider or GO_PROVIDER,
569:                 adapter="opencode",
570:                 is_synthetic=synthetic_vision,
571:             )
572:             final_attachment_paths = [str(p) for p in prepared]
573:         except VisionError as e:
574:             raise DispatchError(
575:                 str(e),
576:                 reason="vision_blocked",
577:                 model=selector.model,
578:                 provider=selector.provider or GO_PROVIDER,
579:             ) from e
580:         except Exception as e:
581:             raise DispatchError(
582:                 f"prepare_vision_input failed: {e}",
583:                 reason="vision_blocked",
584:                 model=selector.model,
585:                 provider=selector.provider or GO_PROVIDER,
586:             ) from e
587: 
588:     bin_path = get_opencode_bin()
589:     norm_model = selector.model
590:     norm_effort = selector.variant or OPENCODE_DEFAULT_EFFORT
591:     provider_name = selector.provider or GO_PROVIDER
592: 
593:     cmd = [
594:         bin_path,
595:         "run",
596:         "--model",
597:         f"{provider_name}/{norm_model}",
598:         "--variant",
599:         norm_effort,
600:     ]
601:     if fmt == "json":
602:         # Raw JSON event stream: tool_use events survive for contamination checks.
603:         cmd.extend(["--format", "json"])
604:     if final_attachment_paths:
605:         for att in final_attachment_paths:
606:             cmd.extend(["-f", str(att)])
607:     # `-f/--file` là array (variadic) và `message` là positional array: không có
608:     # `--`, yargs nuốt prompt làm phần tử -f tiếp theo ⇒ vendor chết với
609:     # "File not found: <toàn prompt>". `--` chốt hết flag/file, prompt luôn
610:     # thành positional kể cả khi prompt bắt đầu bằng '-'.
611:     cmd.append("--")
612:     cmd.append(prompt)
613:     return cmd
614: 
615: 

FILE bin/lib/go_data_gate.py
170: def evaluate_go_data_gate(
171:     *,
172:     data_class: str | None,
173:     prompt: str,
174:     attachments: list[str] | None = None,
175:     synthetic_vision: bool = False,
176:     allow_sensitive_vision: bool = False,
177:     sensitive_confirmation: object = None,
178:     vendor: str | None = None,
179:     model: str | None = None,
180:     workdir: str | None = None,
181: ) -> list[str]:
182:     """Trả warnings khi được phép chạy; raise GoDataGateBlocked khi bị chặn.
183: 
184:     Thứ tự kiểm: cờ data_class → vision/sensitive flags → workdir giả repo →
185:     policy vision theo vendor → capability model → synthetic generator gate →
186:     PII checker.
187: 
188:     ``model``/``workdir`` là tham số ĐỘC LẬP với ``attachments``: builder và
189:     dispatcher đều truyền xuống nên cổng không phụ thuộc một boolean nào của
190:     caller. ``workdir`` KHÔNG được dùng để suy ra repo gốc (artifact synthetic
191:     luôn đọc từ ``REAL_REPO_ROOT``); nó chỉ bị kiểm để chặn "repo giả" do
192:     ``--cd`` trỏ vào một cây khác có manifest riêng.
193:     """
194:     if data_class != DATA_CLASS_CODE_NOPII:
195:         raise _blocked_no_flag(vendor)
196: 
197:     # Dữ liệu thật / sensitive flags luôn block kể cả no files
198:     if allow_sensitive_vision:
199:         raise _blocked_vision(vendor, "allow_sensitive_vision")
200:     if sensitive_confirmation is not None:
201:         raise _blocked_vision(vendor, "sensitive_confirmation")
202: 
203:     # --cd/workdir trỏ vào repo khác có manifest synthetic riêng = repo giả
204:     _reject_shadow_repo(workdir, vendor)
205: 
206:     # Kiểm tra vision / attachment cho từng vendor
207:     if vendor == "hermes":
208:         # hermes giữ block nếu helper chưa support
209:         if attachments or synthetic_vision:
210:             raise _blocked_vision(vendor, "synthetic_vision unsupported on hermes")
211:     elif vendor == "opencode":
212:         if attachments:
213:             if not synthetic_vision:
214:                 raise _blocked_vision(vendor, f"{len(attachments)} attachment without --synthetic-vision")
215:             _assert_model_accepts_vision(model, attachments, vendor)
216:             # Validate synthetic attachments độc lập qua generator gate (không boolean bypass)
217:             try:
218:                 from lib.vision import validate_synthetic_gate, VisionError
219:             except ImportError:
220:                 from bin.lib.vision import validate_synthetic_gate, VisionError
221:             try:
222:                 validate_synthetic_gate(attachments)
223:             except VisionError as exc:
224:                 raise _blocked_vision(vendor, f"synthetic vision validation failed: {exc}") from exc
225:         elif synthetic_vision:
226:             raise _blocked_vision(vendor, "synthetic_vision declared without attachments")
227:     else:
228:         if attachments or synthetic_vision:
229:             raise _blocked_vision(vendor, f"{vendor or 'Go adapter'} does not support vision attachments")
230: 
231:     return _check_prompt_pii(prompt)
