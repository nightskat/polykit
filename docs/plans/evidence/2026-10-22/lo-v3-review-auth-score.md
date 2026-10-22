Grok-4.7 adversarial review vòng3, phần auth-score. CHỈ đọc source NHÚNG dưới đây, KHÔNG tools/agent/file reads. Trả tối đa3 findings thực có severity path:line, reproduction ngắn + fix, ≤25 dòng. Nếu không tìm thấy nói không thấy trong phạm vi này. Ưu tiên bypass/fail-open/auth false-ready/scorer false-correct. Không phân tích lan man, trả kết quả ngay. Context: chỉ synthetic checked-in pinned hashes, real vision cấm; doctor evidence Go TTL1h; benchmark images và PDF tách scope. 947 tests pass nhưng không coi là proof.

FILE bin/lib/doctor_quota.py
274: 
275: def is_explicit_auth_failure_record(record: dict) -> bool:
276:     """Kiểm tra bản ghi có phải lỗi auth tường minh hay không.
277: 
278:     Bao gồm các dấu hiệu: unauthenticated, unauthorized, login required, not logged in.
279:     """
280:     if not isinstance(record, dict):
281:         return False
282:     status = str(record.get("status") or "").lower()
283:     reason = str(record.get("reason") or "").lower()
284:     explicit_markers = ("auth_failure", "unauthenticated", "unauthorized", "login_required", "not_logged_in")
285:     if status in explicit_markers or reason in explicit_markers:
286:         return True
287:     for field in ("error", "stderr", "summary"):
288:         val = str(record.get(field) or "").lower()
289:         if val and any(m in val for m in ("unauthenticated", "unauthorized", "not logged in", "login required")):
290:             return True
291:     return False
292: 
293: 
294: def matches_vendor_criteria(
295:     record: dict,
296:     vendor: str,
297:     provider: str | None = None,
298:     quota_group: str | None = None,
299:     model: str | None = None,
300: ) -> bool:
301:     """Kiểm tra bản ghi evidence có khớp đúng vendor/provider/model/quota group hay không.
302: 
303:     Bản ghi sai vendor, sai provider, sai quota_group hoặc sai model họ provider
304:     bị từ chối (không nhận vơ).
305:     """
306:     if not isinstance(record, dict):
307:         return False
308:     rec_vendor = record.get("vendor")
309:     if not isinstance(rec_vendor, str) or rec_vendor.strip().lower() != vendor.strip().lower():
310:         return False
311: 
312:     # Kiểm tra provider nếu bản ghi có khai
313:     rec_provider = record.get("provider")
314:     if rec_provider is not None and provider is not None:
315:         if rec_provider.strip().lower() != provider.strip().lower():
316:             return False
317: 
318:     # Kiểm tra quota_group nếu bản ghi có khai
319:     rec_qgroup = record.get("quota_group")
320:     if rec_qgroup is not None and quota_group is not None:
321:         if rec_qgroup.strip().lower() != quota_group.strip().lower():
322:             return False
323: 
324:     # Kiểm tra model
325:     rec_model = record.get("model")
326:     if model is not None and rec_model is not None:
327:         if str(rec_model).strip().lower() != str(model).strip().lower():
328:             return False
329:     elif rec_model is not None and provider:
330:         rec_m_str = str(rec_model).strip().lower()
331:         if "/" in rec_m_str:
332:             prefix = rec_m_str.split("/")[0]
333:             if prefix != provider.lower() and prefix in ("openai", "anthropic", "google", "mistral"):
334:                 return False
335: 
336:     return True
337: 
338: 
339: def evaluate_auth_evidence(
340:     records: list[dict],
341:     vendor: str,
342:     now: str | datetime,
343:     ttl: timedelta | None = AUTH_PROBE_TTL,
344:     provider: str | None = None,
345:     quota_group: str | None = None,
346:     model: str | None = None,
347: ) -> dict[str, Any]:
348:     """Hàm THUẦN đánh giá bằng chứng auth từ records cho một vendor tại mốc `now`.
349: 
350:     Quy tắc cốt lõi:
351:     1. Lọc các bản ghi khớp đúng vendor/provider/quota_group/model (không nhận vơ).
352:     2. Bỏ qua bản ghi ts hỏng/thiếu hoặc ở tương lai (now < ts - clock drift).
353:     3. Tín hiệu mới nhất thắng giữa {ok, explicit_auth_failure}.
354:     4. Bản ghi 'ok' chỉ có hiệu lực trong cửa sổ TTL (mặc định AUTH_PROBE_TTL=1h).
355:        Quá hạn -> unverified (stale).
356:     5. Explicit auth failure mới nhất -> authed=False (không bị override bởi ok cũ).
357:     6. Trả về dict:
358:        {
359:            "authed": bool | None,  # True (ready), False (not authed), None (unverified)
360:            "evidence_ts": str | None,
361:            "reason": str | None,
362:            "record": dict | None,
363:        }
364:     """
365:     now_dt = parse_ts(now) if isinstance(now, str) else now
366:     if now_dt is None:
367:         return {"authed": None, "evidence_ts": None, "reason": "invalid_now", "record": None}
368:     if now_dt.tzinfo is None:
369:         now_dt = now_dt.replace(tzinfo=timezone.utc)
370:     else:
371:         now_dt = now_dt.astimezone(timezone.utc)
372: 
373:     valid_events: list[tuple[datetime, int, str, dict]] = []  # (ts_dt, priority, event_type, record)
374: 
375:     for rec in records:
376:         if not matches_vendor_criteria(rec, vendor, provider=provider, quota_group=quota_group, model=model):
377:             continue
378:         ts_dt = parse_ts(rec.get("ts"))
379:         if ts_dt is None:
380:             continue
381:         # Bỏ qua bản ghi ở tương lai (clock drift)
382:         if ts_dt > now_dt:
383:             continue
384: 
385:         if is_explicit_auth_failure_record(rec):
386:             # Ưu tiên auth_failure hơn ok khi cùng timestamp
387:             valid_events.append((ts_dt, 1, "auth_failure", rec))
388:         elif is_ok_record(rec):
389:             valid_events.append((ts_dt, 0, "ok", rec))
390: 
391:     if not valid_events:
392:         return {"authed": None, "evidence_ts": None, "reason": "no_evidence", "record": None}
393: 
394:     # Sắp xếp theo thời gian tăng dần, tie-breaker priority (auth_failure=1 thắng ok=0)
395:     valid_events.sort(key=lambda x: (x[0], x[1]))
396:     latest_ts, _, latest_type, latest_rec = valid_events[-1]
397: 
398:     if latest_type == "auth_failure":
399:         return {
400:             "authed": False,
401:             "evidence_ts": latest_rec.get("ts"),
402:             "reason": latest_rec.get("reason") or "explicit_auth_failure",
403:             "record": latest_rec,
404:         }
405: 
406:     # latest_type == "ok"
407:     age = now_dt - latest_ts
408:     if ttl is not None and age > ttl:
409:         return {
410:             "authed": None,
411:             "evidence_ts": latest_rec.get("ts"),
412:             "reason": f"stale_evidence (quá TTL {ttl})",
413:             "record": latest_rec,
414:         }
415: 
416:     return {
417:         "authed": True,
418:         "evidence_ts": latest_rec.get("ts"),
419:         "reason": "recent_dispatch_success",
420:         "record": latest_rec,
421:     }

FILE bin/lib/vendors.py
338:         # BUG-14: suy auth/quota từ live dispatch evidence — CHỈ lane Go và CHỈ khi có
339:         # mốc thời gian để so TTL. Vendor khác giữ nguyên kết luận của probe mình
340:         # (assume_authed / auth_check_cmd): bằng chứng lane Go không được đổi trạng thái
341:         # claude/codex/agy/gemini, và evidence không có `ts` thì không phải bằng chứng.
342:         # Regression BUG-14 lô 5a: dispatcher gọi detect(spec) KHÔNG truyền `now`; nhánh
343:         # quota cap cũ gọi now.isoformat() trên None → AttributeError, CLI mất luôn JSON.
344:         if _is_go_lane(spec):
345:             from lib.doctor_quota import (
346:                 evaluate_auth_evidence,
347:                 normalize_now_iso,
348:                 quota_capped_since,
349:             )
350:             if records is None:
351:                 records = _read_evidence_safe()
352:             now_iso = normalize_now_iso(now)
353:             if now_iso and records:
354:                 if authed is None:
355:                     auth_res = evaluate_auth_evidence(
356:                         records,
357:                         spec.name,
358:                         now_iso,
359:                         provider=spec.provider,
360:                         quota_group=spec.quota_group,
361:                     )
362:                     if auth_res["authed"] is True:
363:                         authed = True
364:                         error = None
365:                     elif auth_res["authed"] is False:
366:                         authed = False
367:                         error = auth_res.get("reason") or "explicit_auth_failure"
368: 
369:                 # Quota cap newest wins — chỉ hạ vendor vừa được xác minh là authed.
370:                 if authed is True and not quota_capped:
371:                     capped_map = quota_capped_since(records, now_iso)
372:                     if spec.name in capped_map:
373:                         quota_capped = True
374: 
375:         # Catalog động: hỏi CLI, KHÔNG hardcode danh sách dự phòng.

FILE bench/vision/score.py
175: # JSON Output Parser (strict: assistant final text only, no envelopes)
176: # ---------------------------------------------------------------------------
177: 
178: class DuplicateJSONKeyError(ValueError):
179:     """Raised when a JSON object repeats the same key."""
180: 
181: 
182: def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
183:     out: dict[str, Any] = {}
184:     for key, value in pairs:
185:         if key in out:
186:             raise DuplicateJSONKeyError(f"duplicate JSON key: {key!r}")
187:         out[key] = value
188:     return out
189: 
190: 
191: def strict_json_loads(text: str) -> Any:
192:     """json.loads that fails on duplicate object keys (no silent last-wins)."""
193:     return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
194: 
195: 
196: # Field names that only ever appear in a PolyKit dispatch result envelope —
197: # never in a model answer mapping field id -> value.
198: _ENVELOPE_MARKER_KEYS = frozenset(
199:     {"vendor", "exit_code", "served_model", "warnings", "stdout", "stderr", "reason", "latency_ms"}
200: )
201: 
202: # Event type names emitted by `opencode run --format json`.
203: _EVENT_TYPE_NAMES = frozenset(
204:     {"text", "tool_use", "tool_result", "step_start", "step_finish", "error", "reasoning", "thinking"}
205: )
206: 
207: 
208: def looks_like_dispatch_envelope(obj: Any) -> bool:
209:     """True if `obj` looks like a dispatch result envelope rather than predictions."""
210:     if not isinstance(obj, dict):
211:         return False
212:     keys = {str(k).lower() for k in obj}
213:     if keys & _ENVELOPE_MARKER_KEYS:
214:         return True
215:     status = str(obj.get("status", "")).strip().lower()
216:     return "summary" in keys and status in {"ok", "error", "skipped", "blocked", "failed"}
217: 
218: 
219: def is_event_object(obj: Any) -> bool:
220:     """True if `obj` is a single stream event object (not an answer mapping)."""
221:     if not isinstance(obj, dict):
222:         return False
223:     etype = obj.get("type")
224:     if not isinstance(etype, str):
225:         return False
226:     if "part" in obj or "event" in obj:
227:         return True
228:     return etype.strip().lower() in _EVENT_TYPE_NAMES
229: 
230: 
231: def _event_assistant_text(event: Any) -> str | None:
232:     """Return assistant FINAL text carried by one stream event, else None.
233: 
234:     Only `{"type": "text", "part": {"type": "text", "text": ...}}` qualifies.
235:     thought / reasoning / error / tool / step events and user/tool/system roles
236:     are never mined, and no generic "message"/"content"/"delta" key is trusted.
237:     """
238:     if not isinstance(event, dict):
239:         return None
240:     etype = event.get("type")
241:     if not isinstance(etype, str) or etype.strip().lower() != "text":
242:         return None
243:     part = event.get("part")
244:     if not isinstance(part, dict):
245:         return None
246:     ptype = part.get("type")
247:     if ptype is not None and str(ptype).strip().lower() != "text":
248:         return None
249:     role = str(part.get("role") or event.get("role") or "").strip().lower()
250:     if role in ("user", "tool", "system"):
251:         return None
252:     text = part.get("text")
253:     if not isinstance(text, str) or not text.strip():
254:         return None
255:     return text
256: 
257: 
258: def _looks_like_event_stream(raw: str) -> bool:
259:     for line in raw.splitlines():
260:         stripped = line.strip()
261:         if not stripped or not stripped.startswith("{"):
262:             continue
263:         try:
264:             obj = strict_json_loads(stripped)
265:         except Exception:
266:             return False
267:         return isinstance(obj, dict) and isinstance(obj.get("type"), str)
268:     return False
269: 
270: 
271: def _parse_event_stream(raw: str) -> list[dict[str, Any]]:
272:     events: list[dict[str, Any]] = []
273:     for line in raw.splitlines():
274:         stripped = line.strip()
275:         if not stripped or not stripped.startswith("{"):
276:             continue
277:         try:
278:             obj = strict_json_loads(stripped)
279:         except Exception:
280:             # Not a decodable event: never mine text from it.
281:             continue
282:         if isinstance(obj, dict):
283:             events.append(obj)
284:     return events
285: 
286: 
287: def extract_stream_text_from_jsonl(raw: str) -> str:
288:     """Extract ONLY assistant final text from opencode JSONL stream events.
289: 
290:     Kept under its original name for callers, but the old permissive scan
291:     (which mined thought/reasoning/message/error/tool payloads) is gone.
292:     """
293:     if not isinstance(raw, str) or not raw.strip():
294:         return ""
295:     events = _parse_event_stream(raw)
296:     texts = [t for t in (_event_assistant_text(e) for e in events) if t]
297:     return "\n".join(texts)
298: 
299: 
300: _TOOL_MARKERS = ("tool_use", "tool_result", "tool_call", "tool-invocation", "tooluse")
301: 
302: 
303: def _has_tool_marker(node: Any) -> bool:
304:     if not isinstance(node, dict):
305:         return False
306:     etype = str(node.get("type", "")).strip().lower()
307:     if "tool" in etype:
308:         return True
309:     if str(node.get("role", "")).strip().lower() == "tool":
310:         return True
311:     part = node.get("part")
312:     if isinstance(part, dict):
313:         ptype = str(part.get("type", "")).strip().lower()
314:         if "tool" in ptype or ptype in _TOOL_MARKERS:
315:             return True
316:         if part.get("tool") or part.get("toolName") or part.get("callID"):
317:             return True
318:     return False
319: 
320: 
321: def detect_tool_events(raw_text: str) -> bool:
322:     """Detect tool usage (read/bash/...) inside an opencode JSONL event stream.
323: 
324:     Unsandboxed runs cannot be trusted to ignore tools: if the model invoked
325:     any tool we must flag the call as contaminated instead of counting its
326:     predictions as visual accuracy.
327:     """
328:     if not isinstance(raw_text, str) or not raw_text.strip():
329:         return False
330: 
331:     stripped = raw_text.strip()
332:     try:
333:         single = strict_json_loads(stripped)
334:     except Exception:
335:         single = None
336:     if isinstance(single, dict) and is_event_object(single):
337:         return _has_tool_marker(single)
338: 
339:     return any(_has_tool_marker(ev) for ev in _parse_event_stream(raw_text))
340: 
341: 
342: def _accept_prediction_object(obj: Any) -> dict[str, Any] | None:
343:     if not isinstance(obj, dict):
344:         return None
345:     if is_event_object(obj):

FILE bench/vision/run.py
350: 
351:     quota_attempts = 0
352:     inference_success = 0
353:     contaminated_calls: list[dict[str, Any]] = []
354:     predictions_by_scope: dict[str, dict[str, Any]] = {"images": {}, "pdf": {}}
355:     call_records: list[dict[str, Any]] = []
356: 
357:     dispatch_script = REPO_ROOT / "bin" / "dispatch.py"
358: 
359:     for idx, task in enumerate(target_tasks, start=1):
360:         task_id = task["task_id"]
361:         doc_name = task["document"]
362:         file_path = task["file_path"]
363:         task_fields = task["fields"]
364:         task_field_ids = _field_ids(task_fields)
365: 
366:         prompt_text = build_prompt_for_fields(doc_name, task_fields)
367:         prompt_file = prompts_dir / f"prompt_{task_id}.txt"
368:         with open(prompt_file, "w", encoding="utf-8") as pf:
369:             pf.write(prompt_text)
370: 
371:         # Empty scratch cwd: an unsandboxed model starts with no workspace
372:         # containing ground truth. The vision gate's trusted root is a module
373:         # constant (REAL_REPO_ROOT), so --cd cannot widen or move it.
374:         call_cwd = scratch_root / task_id
375:         call_cwd.mkdir(parents=True, exist_ok=True)
376: 
377:         cmd = [
378:             sys.executable,
379:             str(dispatch_script),
380:             "opencode",
381:             "--model", model,
382:             "--effort", effort,
383:             "--data-class", "code-nopii",
384:             "--synthetic-vision",
385:             "--file", str(file_path),
386:             "--timeout", str(timeout),
387:             "--format", dispatch_format,
388:             "--cd", str(call_cwd),
389:             "--result-json",
390:             "--prompt-file", str(prompt_file),
391:         ]
392: 
393:         sys.stderr.write(f"[{idx}/{len(target_tasks)}] Dispatching {doc_name} to {model} (effort={effort})...\n")
394: 
395:         quota_attempts += 1
396:         retcode, stdout, stderr, latency = run_dispatch_call(
397:             cmd, timeout=timeout, dry_run=dry_run, wrapper_grace=wrapper_grace
398:         )
399: 
400:         # --- Strict acceptance: retcode==0 AND dispatch status=="ok" ---------
401:         # No fallback: a dispatch envelope, an error payload, or stray prose is
402:         # never parsed as predictions. Unaccepted calls simply score 0 on their
403:         # own task fields (never excluded from the denominator).
404:         dispatch_obj: dict[str, Any] | None = None
405:         model_stdout = ""
406:         parsed_predictions: dict[str, Any] | None = None
407:         contaminated = False
408:         status = "failed"
409: 
410:         if dry_run:
411:             status = "dry_run"
412:         elif retcode != 0:
413:             status = f"exit_{retcode}"
414:         else:
415:             try:
416:                 loaded = strict_json_loads(stdout)
417:             except Exception:
418:                 loaded = None
419:             if not isinstance(loaded, dict):
420:                 status = "invalid_dispatch_envelope"
421:             else:
422:                 dispatch_obj = loaded
423:                 if dispatch_obj.get("status") != "ok":
424:                     status = f"dispatch_{dispatch_obj.get('status', 'unknown')}"
425:                 else:
426:                     model_stdout = dispatch_obj.get("stdout") or ""
427:                     contaminated = detect_tool_events(model_stdout)
428:                     raw_predictions = parse_json_response(model_stdout)
429:                     if raw_predictions is None:
430:                         status = "json_parse_failed"
431:                     else:
432:                         # Only the fields this task asked for are ever persisted.
433:                         filtered = {
434:                             k: v for k, v in raw_predictions.items() if k in task_field_ids
435:                         }
436:                         if not filtered:
437:                             status = "no_task_fields"
438:                         elif contaminated:
439:                             # Tool use = unsandboxed contamination: keep the
440:                             # evidence, never count it as vision accuracy.
441:                             status = "contaminated_tools"
442:                             parsed_predictions = filtered
443:                         else:
444:                             status = "ok"
445:                             parsed_predictions = filtered
446:                             inference_success += 1
447:                             predictions_by_scope[task["scope"]].update(filtered)
448: 
449:         if contaminated or status == "contaminated_tools":
450:             contaminated_calls.append({
451:                 "call_index": idx,
452:                 "task_id": task_id,
453:                 "scope": task["scope"],
454:                 "status": status,
455:             })
456: 
457:         # Per-call score over THIS task's fields only.
458:         call_score = score_predictions(
459:             gt_data,
460:             parsed_predictions if (parsed_predictions and status == "ok") else {},
461:             field_ids=task_field_ids,
462:         )
463: 
464:         call_record: dict[str, Any] = {
465:             "call_index": idx,
466:             "task_id": task_id,
467:             "document": doc_name,
468:             "scope": task["scope"],
469:             "file_path": str(file_path),
470:             "workdir": str(call_cwd),
471:             "command": cmd,
472:             "latency_seconds": round(latency, 4),
473:             "returncode": retcode,
474:             "status": status,
475:             "contaminated": contaminated,
476:             "contamination_status": status if contaminated else None,
477:             "dispatch_status": (dispatch_obj or {}).get("status"),
478:             "field_ids": sorted(task_field_ids),
479:             "score": call_score,
480:             "raw_stdout": stdout,
481:             "raw_stderr": stderr,
482:             "model_stdout": model_stdout,
483:             "parsed_predictions": parsed_predictions,
484:             "timestamp": _utc_now(),
485:         }
486: 
487:         # Persist raw call result immediately
488:         raw_call_file = raw_calls_dir / f"call_{idx:02d}_{task_id}.json"
489:         with open(raw_call_file, "w", encoding="utf-8") as rf:
490:             json.dump(call_record, rf, ensure_ascii=False, indent=2)
491: 
492:         call_records.append(call_record)
493: 
494:     # --- Scope scoring: disjoint denominators, never full GT by accident -----
495:     scope_reports: dict[str, dict[str, Any]] = {}
496:     for scope in ("images", "pdf"):
497:         if scope in scope_field_ids:
498:             scope_reports[scope] = score_predictions(
499:                 gt_data,
500:                 predictions_by_scope[scope],
501:                 field_ids=scope_field_ids[scope],
502:             )
503: 
504:     if mode == "all":
505:         primary_report = _merge_scope_reports(scope_reports)
506:     else:
507:         primary_report = scope_reports[mode]
508: 
509:     scoring_summary = {
510:         "primary_mode": mode,
511:         "images": _condense(scope_reports.get("images")),
512:         "pdf": _condense(scope_reports.get("pdf")),
513:         "images_applicable": "images" in scope_reports,
514:         "pdf_applicable": "pdf" in scope_reports,
515:         "images_field_count": len(scope_field_ids.get("images", set())),
516:         "pdf_field_count": len(scope_field_ids.get("pdf", set())),
517:         "excluded_contaminated_calls": [c["task_id"] for c in contaminated_calls],
518:         "note": (
519:             "images and pdf are scored on disjoint field sets; the primary figure "
520:             "follows --mode (mode=all = additive merge of both scopes)."
