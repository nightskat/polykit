Grok review gate vòng3 cuối: chỉ snippet này, không tools. Tối đa2 finding THỰC + severity/repro 2 dòng, hoặc không thấy. Context upstream caller requires explicit synthetic + code-nopii, model policy, only opencode. Root fixed module REAL_REPO_ROOT (not caller), registry pinned checked-in SHA256, source file hash checked below gate; output PDF converts fresh private directory. Caller cannot override trust. Check malformed manifest, omitted requested entry, path/symlink. Return NOW concise ≤15 lines, no code generation.
440: 
441:     # 1. Symlink checks on directory hierarchy and manifest
442:     check_no_symlinks(synth_dir, root)
443:     check_no_symlinks(manifest_path, root)
444: 
445:     # 2. Check manifest existence & regular file
446:     if not manifest_path.exists() or not manifest_path.is_file():
447:         raise VisionBlockedError(f"Synthetic manifest not found: {manifest_path}")
448: 
449:     # 3. Parse manifest
450:     try:
451:         with open(manifest_path, "r", encoding="utf-8") as f:
452:             manifest = json.load(f)
453:     except Exception as e:
454:         raise VisionBlockedError(f"Malformed synthetic manifest JSON: {e}") from e
455: 
456:     if not isinstance(manifest, dict):
457:         raise VisionBlockedError("Manifest root must be a JSON object")
458: 
459:     # ``type(...) is int`` (không dùng ==) để loại schema_version=true (bool),
460:     # vì True == 1 trong Python và sẽ lọt cổng nếu chỉ so sánh giá trị.
461:     schema_version = manifest.get("schema_version")
462:     if type(schema_version) is not int or schema_version != EXPECTED_MANIFEST_SCHEMA_VERSION:
463:         raise VisionBlockedError(
464:             f"Invalid manifest schema_version: {manifest.get('schema_version')!r}"
465:         )
466: 
467:     if manifest.get("generator") != EXPECTED_MANIFEST_GENERATOR:
468:         raise VisionBlockedError(
469:             f"Invalid manifest generator: {manifest.get('generator')!r}"
470:         )
471: 
472:     manifest_files = manifest.get("files")
473:     if not isinstance(manifest_files, list) or not manifest_files:
474:         raise VisionBlockedError("Manifest files must be a non-empty list")
475: 
476:     # 4. Verify manifest against trusted generator registry (pinned artifact)
477:     seen_manifest_files: set[str] = set()
478:     manifest_map: dict[str, dict[str, Any]] = {}
479: 
480:     for entry in manifest_files:
481:         if not isinstance(entry, dict):
482:             raise VisionBlockedError("Manifest file entry must be a dictionary")
483: 
484:         fname = entry.get("path")
485:         if not isinstance(fname, str) or not fname:
486:             raise VisionBlockedError("Manifest file missing path string")
487:         # Manifest là danh sách đóng trong MỘT thư mục: chỉ nhận tên file trần,
488:         # không separator, không '.', không '..', không đường dẫn tuyệt đối.
489:         if fname in (".", "..") or "/" in fname or "\\" in fname or Path(fname).name != fname:
490:             raise VisionBlockedError(
491:                 f"Manifest file path must be a plain filename: {fname!r}"
492:             )
493:         if fname in seen_manifest_files:
494:             raise VisionBlockedError(f"Duplicate file in manifest: {fname}")
495:         seen_manifest_files.add(fname)
496: 
497:         if fname not in trusted_reg:
498:             raise VisionBlockedError(
499:                 f"Manifest file {fname} is not in trusted generator registry"
500:             )
501: 
502:         record = trusted_reg[fname]
503:         if not isinstance(record, dict):
504:             raise VisionBlockedError(f"Trusted registry entry for {fname} is malformed")
505: 
506:         sha = entry.get("sha256")
507:         if not isinstance(sha, str) or not _SHA256_HEX_RE.match(sha.lower()):
508:             raise VisionBlockedError(f"Manifest file {fname} missing/invalid sha256")
509: 
510:         expected_sha = str(record.get("sha256", "")).lower()
511:         if not _SHA256_HEX_RE.match(expected_sha):
512:             raise VisionBlockedError(f"Trusted registry sha256 for {fname} is malformed")
513:         if sha.lower() != expected_sha:
514:             raise VisionBlockedError(
515:                 f"Manifest sha256 mismatch for {fname} against trusted generator registry"
516:             )
517: 
518:         # bytes phải là int thật (bool bị loại vì True == 1) và khớp registry.
519:         expected_bytes = record.get("bytes")
520:         if type(expected_bytes) is not int or expected_bytes <= 0:
521:             raise VisionBlockedError(f"Trusted registry bytes for {fname} is malformed")
522:         entry_bytes = entry.get("bytes")
523:         if type(entry_bytes) is not int or entry_bytes != expected_bytes:
524:             raise VisionBlockedError(
525:                 f"Manifest byte size mismatch for {fname} against trusted generator registry"
526:             )
527: 
528:         # format (nếu khai) phải khớp registry; rel_path (nếu khai) phải đúng cây.
529:         declared_format = entry.get("format")
530:         expected_format = record.get("format")
531:         if declared_format is not None:
532:             if (
533:                 not isinstance(declared_format, str)
534:                 or not isinstance(expected_format, str)
535:                 or declared_format.upper() != expected_format.upper()
536:             ):
537:                 raise VisionBlockedError(f"Manifest format mismatch for {fname}")
538: 
539:         declared_rel = entry.get("rel_path")
540:         expected_rel = record.get("rel_path")
541:         if declared_rel is not None and declared_rel != expected_rel:
542:             raise VisionBlockedError(f"Manifest rel_path mismatch for {fname}")
543: 
544:         manifest_map[fname] = entry
545: 
546:     # 5. Validate caller attachments
547:     validated: list[VisionAttachment] = []
548:     seen_attachments: set[str] = set()
549: 
550:     for item in files:
551:         if not item:
552:             raise VisionFormatError("Empty file path provided")
553:         p = Path(item)
554: 
555:         # Path traversal check
556:         if ".." in p.parts:
557:             raise VisionSecurityError(f"Path traversal detected in attachment: {item}")
558: 
559:         # Resolve target path relative to synth_dir
560:         if p.is_absolute():
561:             target_path = p
562:         elif len(p.parts) == 1:
563:             target_path = synth_dir / p.name
564:         else:
565:             # e.g. bench/vision/synthetic/page_01.png
566:             target_path = root / p
567: 
568:         # Check outside synthetic dir
569:         try:
570:             rel = target_path.resolve(strict=False).relative_to(synth_dir.resolve(strict=False))
571:             if len(rel.parts) != 1:
572:                 raise VisionSecurityError(
573:                     f"Attachment {item} must be directly inside {synth_dir}"
574:                 )
575:         except (ValueError, RuntimeError):
576:             raise VisionSecurityError(
577:                 f"Attachment {item} is outside fixed synthetic directory: {synth_dir}"
578:             )
579: 
580:         filename = target_path.name
581:         if filename in seen_attachments:
582:             raise VisionBlockedError(f"Duplicate attachment provided: {filename}")
583:         seen_attachments.add(filename)
584: 
585:         # Check symlink on file and all ancestors up to root
586:         check_no_symlinks(target_path, root)
587: 
588:         # Check file exists and is regular file
589:         if not target_path.exists():
590:             raise VisionFormatError(f"Synthetic file not found: {target_path}")
591:         if not target_path.is_file():
592:             raise VisionFormatError(f"Not a regular file: {target_path}")
593: 
594:         # Kiểm tra kích thước trước khi tra registry: file rỗng/quá trần trong
595:         # synthetic dir luôn bị chặn, không cần khai báo trong manifest.
596:         actual_size = target_path.stat().st_size
597:         if actual_size == 0:
598:             raise VisionFormatError(f"Synthetic file is empty: {filename}")
599:         if actual_size > max_bytes:
600:             raise VisionQuotaError(
601:                 f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
602:             )
603: 
604:         if filename not in trusted_reg:
605:             raise VisionBlockedError(
606:                 f"File {filename} is not in trusted synthetic generator registry"
607:             )
608: 
609:         # Manifest là danh sách ĐÓNG: file có trong registry nhưng generator
610:         # không khai báo trong manifest thì không được coi là synthetic hợp lệ.
611:         if filename not in manifest_map:
612:             raise VisionBlockedError(
613:                 f"Requested file {filename} is not declared in the synthetic manifest"
614:             )
615:         manifest_sha = str(manifest_map[filename].get("sha256", "")).lower()
616:         if manifest_sha != trusted_reg[filename]["sha256"].lower():
617:             raise VisionBlockedError(
618:                 f"Manifest sha256 mismatch for {filename} against trusted generator registry"
619:             )
620: 
621:         actual_size = target_path.stat().st_size
622:         if actual_size == 0:
623:             raise VisionFormatError(f"Synthetic file is empty: {filename}")
624:         if actual_size > max_bytes:
625:             raise VisionQuotaError(
626:                 f"Synthetic file {filename} exceeds max size {max_bytes} bytes"
627:             )
628: 