# AI Clipper code map

A map for people and AI agents: what each file does, and where the important functions live.
AI Clipper is a Python (FastAPI) app that turns YouTube, Twitch and Kick videos and live streams into vertical 9:16 clips with captions.

**Line numbers drift as code changes.** Treat them as a starting point and confirm with a search, e.g.
`grep -n "^def _run_job" studio/jobs.py`. Route line numbers point at the `@app.` decorator.

Start with [AGENTS.md](AGENTS.md) for how to run, test and the house rules. Run tests with `python tests/run.py`.

---

## Quick "where is…" index

| I want to change… | Look in |
|---|---|
| A web route / API endpoint | `studio/server.py` (routes listed below) |
| Who is signed in, sessions, passwords, Google sign-in | `studio/auth.py`, `studio/ctx.py` |
| The video pipeline (link → clips) | `studio/jobs.py` → `_run_job` |
| yt-dlp downloads, ffprobe, audio | `studio/media.py` (`_ydl` builds every yt-dlp client) |
| Speech to text | `studio/transcribe.py`, `studio/asr_worker.py` (GPU box) |
| How moments are picked, prompts, captions translation | `studio/brain.py` |
| Calling the AI provider, adding a provider | `studio/ai.py` → `PROVIDERS` |
| Rendering, layouts, caption styles, hook heading | `studio/render.py` |
| Webcam box detection | `studio/facecam.py` |
| Ad breaks / frozen screens | `studio/quality.py` |
| Live recording and live clipping | `studio/live.py` → `class Session` |
| Posting to YouTube / Instagram / TikTok | `studio/posting.py` (queue), `studio/accounts.py` (OAuth + upload calls) |
| A setting / env var | `studio/config.py` |
| Database tables | `studio/db.py` |
| The signed-in web app UI | `web/index.html` (one file, no build step) |
| Admin dashboard | `studio/admin.py`, `web/admin.html` |

## Folder layout

```
peakcut/
  studio/        Python backend (one module per concern, listed below)
  web/           HTML pages + two canvas background scripts + brand/ images
  tests/         run.py + test_*.py (each runs against a throwaway server)
  deploy/        Caddy, nginx, Traefik and GPU deployment configs
  data/          Runtime data: users, jobs, clips, models, database (not code)
```

---

## How a video becomes clips

1. `server.create_from_link` / `create_from_file` → `jobs.create()` makes the job folder and `job.json`, queues it on the per-user fair queue (`jobs._FairQueue`).
2. `jobs._worker()` threads pick it up (gated by `load.busy()`) and call `jobs._run_job()`.
3. **Source:** link → `media.info()` (single video, not live) → `media.save_thumb()` → `media.download_audio()`. Short videos also get `media.download()` in the background; long ones (>40 min) fetch pieces later with `media.download_section()`. Uploads → `media.probe()`.
4. **Audio:** `media.extract_audio()` (16 kHz WAV) → `load_audio()` → `loudness_per_second()`.
5. **Transcript:** YouTube links try `media.youtube_words()` (checked by `jobs._covers`). Otherwise `transcribe.transcribe()` on 10-minute blocks, local CPU/GPU or the remote `asr_worker`. Saved to `words.json`.
6. **Pick moments:** `brain.find_clips()` (AI via `ai.call`, or `brain.fallback_by_loudness` with no AI). `quality.static_ranges()` drops ad breaks/frozen screens. `jobs._facecam()` → `facecam.detect()` for gameplay layouts.
7. **Render:** each clip → `jobs._fetch_piece()` (long videos) → `jobs.render_one()` → `_caption_words()` (English/Roman via `brain.english_captions`, `roman.words`) → `render.render_clip()` → `geometry`, `build_ass`, `_filter`, `_render_in` (NVENC → QSV → x264).
8. **Finish:** `jobs._wait_for_clips()` enforces `CLIP_MINUTES`; job set done; `posting.on_clip_ready()` queues autoposts; `notices.add()` rings the bell.
9. **Later:** `jobs.more_clips()` reuses `words.json`; `jobs.request_render()` re-makes one edited clip. After a restart `jobs._pick_up_after_restart()` resumes from the last saved block.

The page polls `GET /api/sync`; anything that changes what a user sees must call `ctx.bump()`.

---

## studio/ — backend

### Web layer

#### studio/server.py
Every HTTP route, the `Gate` middleware (sign-in, cross-site protection, size caps, security headers, fast unchanged `/api/sync`), gzip `Compress`, chunked uploads, and `main()` (uvicorn). Run: `python -m studio.server`.
- `_startup()` (59) — init DB, clear old uploads, install fonts, fetch speech model, start jobs/live/posting/update checks
- `class Gate` (80) — ASGI middleware run before every request
- `class Compress` (215) — gzip for text responses
- `_ip(request)` (251), `_from_cdn(addr)` (234) — visitor address for rate limits
- `_from_here(req, must_say)` (267), `_own_address(host)` (282) — same-site and Host checks
- `_me(request)` (297), `_admin(request)` (301), `_need_verified()` (309) — who is asking
- `_page(name, shared)` (315) — serve an HTML page
- `_signed_in(...)` (444) — start session + set cookie
- `_job_or_404(jid)` (585), `_job_slots()` (592), `_quota()` (605), `_throttle(...)` (625) — guards
- `_lookup(fn, *a)` (632) — link/channel preview, max 8 at once server-wide
- `_sync_token()` (652), `_sync_unchanged(v)` (656), `sync(v)` (668) — page polling
- `_up_root()` (790), `_up_sweep()` (796), `_up_get(upid)` (806) — chunked upload storage
- `_pairs(v, limit)` (970), `_channel_ok(body)` (1051) — input validation
- `_on_this_computer(request)` (1403) — local-only actions (open folder)
- `main()` (1586)

**Pages and public files**
- `GET /` landing (326) · `/robots.txt` (338) · `/sitemap.xml` (345) · `/login`, `/signup` (357) · `/reset` (362)
- `/privacy`, `/terms`, `/acceptable-use` (376) · `/app`, `/app/{rest}` (399) · `/admin…` (406) · `/healthz` (412)
- `/brand/{name}` (419) · `/assets/{name}` (426) · `/favicon.ico` (433) · `GET /pub/{token}.mp4` signed clip link for platforms (1388)

**Auth and account**
- `GET /api/public` (439) · `POST /api/auth/signup` (452) · `/resend-verification` (464) · `GET /auth/verify` (479)
- `POST /api/auth/forgot` (488) · `/reset` (500) · `/login` (510) · `/logout` (522) · `GET /api/auth/me` (530) · `POST /api/auth/password` (535)
- `GET /auth/google/start` (548) · `/auth/google/callback` (559)
- `POST /api/account/delete` (1024) · `GET /api/me/photo` (1138) · `POST /api/feedback` (1093)
- `GET /api/notifications` (1125) · `POST /api/notifications/read` (1131)

**Videos, jobs and clips**
- `GET /api/status` (572) · `GET /api/sync` (667) · `GET /api/jobs` (679) · `GET /api/jobs/{jid}` (684)
- `GET /api/preview` → `link_preview` (689) — checks a pasted link before work starts
- `POST /api/jobs` (710) · `POST /api/upload` (740)
- `POST /api/upload/start` (819) · `PUT /api/upload/{upid}/{n}` (863) · `POST …/finish` (887) · `DELETE /api/upload/{upid}` (924)
- `POST /api/jobs/{jid}/clips/{cid}/render` (931) · `POST /api/jobs/{jid}/more` (947)
- `DELETE /api/jobs/{jid}` (961) · `DELETE /api/jobs/{jid}/clips/{cid}` (979) · `POST /api/bulk/delete` (990)
- `GET /api/clips.zip` (998) · `GET /media/{jid}/{name}` (1040)

**Creators and live**
- `GET/POST /api/creators` (1179/1184) · `PUT /api/creators/{cid}` (1198) · `DELETE` (1012) · `GET …/avatar` (1166)
- `GET /api/channel-preview` (1147) · `POST /api/creators/{cid}/live` (1218) · `POST /api/live/{jid}/stop` (1237) · `POST /api/live/{jid}/clip` (1246)

**AI and usage**
- `GET /api/usage` (1262) · `GET/PUT /api/ai` (1273/1279) · `POST /api/ai/models` (1293) · `POST /api/ai/test` (1307) · `GET /api/overview` (1320)

**Settings, connected accounts, posting**
- `GET/PUT /api/settings` (1325/1330) · `GET /api/accounts` (1339) · `DELETE /api/accounts/{aid}` (1344)
- `GET /oauth/{platform}/start` (1358) · `/callback` (1368)
- `POST /api/posts` (1495) · `POST /api/posts/{pid}/{action}` (1507) · `POST /api/alerts/test` (1518)

**Setup, hardware, storage, apps**
- `GET /api/setup` (1409) · `GET/PUT /api/hardware` (1417/1424) · `GET/PUT /api/storage` (1437/1466)
- `POST /api/storage/open` (1444) · `POST /api/storage/pick` (1457) · `GET/PUT /api/apps` (1480/1486)

**Admin** (only `is_admin`; others get 404)
- `GET /api/admin/email-preview` (1066) · `POST /api/admin/test-email` (1080)
- `GET /api/admin/feedback` (1107) · `POST /api/admin/feedback/{fid}` (1114)
- `GET /api/admin/overview` (1543) · `GET /api/admin/users/{uid}` (1549)
- `POST /api/admin/users/{uid}/disabled` (1558) · `POST /api/admin/users/{uid}/delete` (1567)

#### studio/ctx.py
Which user the current code runs for (a context variable). Requests set it from the session; background threads set it themselves.
- `NoUser` (14) · `uid()` (18) · `uid_or_none()` (25) · `set_uid(u)` (29)
- `as_user(u)` (35) — run a block as a user · `bind(fn)` (43) — carry the user onto another thread
- `bump(u)` (63) — bump the change counter `/api/sync` watches · `version(u)` (69)

#### studio/db.py
SQLAlchemy engine (PostgreSQL via `DATABASE_URL`, else SQLite with WAL) and tables: users, sessions, usage, email_ok, email_tokens, feedback, notices, admin_log.
- `init()` (115) — create tables · `now()` (119)

#### studio/auth.py
Accounts and sign-in: scrypt passwords, Google sign-in, session cookies, one-time email links, login throttling, local single-owner mode.
- `AuthError` (25) · `hash_password` (30) · `verify_password` (36) · `_check_password_rules` (49)
- `throttle(key, limit, window)` (57) — generic rate limit
- `public(u)` (73) · `is_verified` (94) · `mark_verified` (104)
- `_make_link` (110) · `_use_link` (121) · `send_verify` (136) · `verify_link` (144) · `forgot` (150) · `reset_password` (163)
- `get_user` (174) · `user_ids` (179) · `_create` (184) · `signup` (202) · `login` (208) · `change_password` (224)
- `local_user()` (244) — the one owner when `PEAKCUT_ACCOUNTS` is off
- `start_session` (267) · `user_for(token)` (281) · `forget` (303) · `seen_recently` (309) · `touch` (316) · `end_session` (329) · `cookie_args` (335)
- `google_ready` (341) · `google_url` (345) · `google_finish` (362) · `save_photo` (408) · `photo` (426)

#### studio/account.py
Permanent deletions and zip downloads; refuses anything still being made or recorded.
- `Busy` (13) · `_busy(job)` (17) · `delete_clip` (22) · `delete_many` (54) · `zip_clips` (78) · `delete_creator` (114) · `delete_account` (134)

#### studio/accounts.py
Connected social accounts (YouTube, Instagram, TikTok), per-user settings, platform app keys, signed one-hour clip links, and each platform's upload and view-count calls.
- Storage: `_dir` (38) · `_read` (44) · `_write` (54) · `SETTING_DEFAULTS` (26) · `APPS` (71) · `APP_FOR` (74)
- Platform apps: `_apps_file` (78) · `_apps_saved` (82) · `app_keys` (97) · `can_connect` (108) · `redirect_for` (112) · `apps_public` (116) · `save_app` (128)
- OAuth: `_new_state` (157) · `_take_state` (165) · `connect_url` (171) · `connect_finish` (190)
- Clip links: `_link_key` (201) · `clip_link` (214) · `read_clip_link` (221)
- Settings: `settings` (240) · `save_settings` (247) · `public_settings` (268)
- Accounts: `_all` (274) · `get` (278) · `list_accounts` (282) · `handle_of` (287) · `_put` (308) · `remove` (314) · `_check` (319)
- YouTube: `youtube_ready` (326) · `_youtube_finish` (330) · `_yt_token` (350) · `youtube_upload` (363) · `youtube_views` (380)
- Instagram: `_instagram_finish` (392) · `_instagram_save` (407) · `instagram_add` (418) · `_ig_token` (423) · `instagram_upload` (435) · `instagram_views` (474)
- TikTok: `_tt` (484) · `_tt_tokens` (500) · `_tiktok_finish` (506) · `_tt_token` (522) · `_tt_post` (533) · `_tiktok_creator` (539) · `TT_PRIVACY` (544) · `_tt_chunks` (548) · `tiktok_upload` (555)

#### studio/admin.py
Admin dashboard logic. Admins see accounts and AI use, never videos or clips. Admin is granted only from the command line.
- `Refused` (20) · `_day` (27) · `_log` (31) · `overview()` (37) · `user_detail` (100) · `set_disabled` (121) · `set_admin` (142)
- `_cli(argv)` (155) — `python -m studio.admin list | grant <email> | revoke <email>`

### Video pipeline

#### studio/jobs.py
The job pipeline and fair queue: saving/loading `job.json`, `_run_job`, re-making clips, more clips, restart recovery.
- Settings: `DEFAULTS` (111) · `LIMITS` (115) · `HIDDEN` (150) · `CLIP_MINUTES` (450) · `LONG_VIDEO` (494) · `PAD` (495) · `BLOCK` (541) · `PROGRESSIVE_FROM` (542)
- State: `_q` (104) · `_live_q` (105) · `_jobs` (106) · `_by_user` (107) · `_lock` (108) · `on_clip_ready` (109)
- `_FairQueue` (17) — per-user lines served in turn; `put` (44), `get` (56), `done` (39), `ahead` (84), `_room` (32)
- `clean_options` (118) · `job_dir` (146) · `public(job)` (153) · `save` (170) · `_set` (187) · `_remap` (193)
- `_load_file` (202) · `load_user` (240) · `load_all` (246) · `all_jobs` (252) · `list_jobs` (258) · `get` (264)
- `busy_count` (270) · `waiting_total` (275) · `queue_epoch` (279) · `running_now` (283)
- `create(...)` (287) · `enqueue` (311) · `submit(fn)` (316) · `submit_live` (321) · `_live_worker` (326) · `delete` (335)
- `request_render(jid, cid, changes)` (346) — re-make one edited clip
- `_own_handle` (375) · `_credit_tag` (388) — "via X · @handle" line on clips
- `render_one(job, clip, words)` (398) · `_caption_words` (432) · `_wait_for_clips` (453)
- `_english_part` (478) · `_piece_again` (498) · `_fetch_piece` (519) · `_covers` (545) · `_facecam(job)` (553)
- **`_run_job(job)` (573)** — the whole pipeline; moments from every block are collected in `picks`, then `_best_of` chooses across the whole video
- `more_clips` (825) · `_more_clips` (842) · `_worker` (901) · `_pick_up_after_restart` (939) · `start()` (951)

#### studio/media.py
Getting video in: link checks, yt-dlp, ffprobe, audio, loudness, YouTube transcripts, and the YouTube-refusal pause.
- `NO_WINDOW` (15) · `YT_PAUSE` (21) · `YT_BLOCKED` (23) · `_BOT_CHECK` (25) · `YouTubeBlocked` (28)
- `is_youtube` (32) · `youtube_paused` (38) · `check_youtube` (42) · `note_refusal` (48) · `_youtube_guard` (61)
- `site_allowed(url)` (76) · `run(cmd)` (87) — ffmpeg/ffprobe runner
- **`_ydl(opts)` (105)** — every yt-dlp client: YouTube cookies (YouTube only), remote JS challenge solver (`remote_components`), timeouts
- `_video_format` (121) · `_biggest` (125)
- `info(url)` (133) · `youtube_words` (142) · `youtube_english_words` (161) · `_caption_words` (181)
- `preview(url)` (207) — used by `/api/preview`; cached in `_PREVIEWS` (204) · `save_thumb` (238)
- `download_audio` (260) · `download` (273) · `download_section` (281) · `find_offset` (295)
- `probe` (308) · `extract_audio` (325) · `load_audio` (332) · `loudness_per_second` (338)

#### studio/transcribe.py
Speech to text with word timestamps (Parakeet via sherpa-onnx), on this machine and/or the remote GPU worker.
- Settings: `PROVIDER` (21) · `THREADS` (23) · `COPIES` (24) · `REMOTE` (29, `PEAKCUT_ASR_URL`) · `REMOTE_TOKEN` (30) · `REMOTE_BATCH` (31) · `REMOTE_PARALLEL` (32) · `REMOTE_SLOTS` (35) · `CPU_MODEL` (139) · `BATCH` (280)
- `model_ready` (39) · `_model_files` (44) · `_sherpa` (58) · `_load_sherpa` (67) — Windows long-path and CUDA DLL workarounds
- `_make` (144) · `_writes_words` (157) · `_back_to_processor` (173) · `_new` (183) · `_take` (211) · `_take_now` (232) · `_recognizer` (253)
- `_chunks` (260) · `_words` (284) · `decode_pieces` (309) · `_remote_ok` (324) · `_decode_remote` (328)
- **`transcribe(audio, on_progress)` (342)** — main entry, returns `[{w, s, e}]`

#### studio/asr_worker.py
Small FastAPI service for a GPU machine: takes audio pieces, returns tokens and timestamps. No accounts or files.
- `TOKEN` (21) · `PORT` (22) · `CARD_BATCH` (23) · `MAX_BODY` (24) · `MAX_PIECE` (25) · `app` (27)
- `GET /healthz` → `healthz` (33) · `POST /decode` → `decode` (41) · `main()` (77)

#### studio/render.py
Turns a time range into a 9:16 MP4 with word-by-word captions, a hook heading and a cover image.
- `W`, `H` (11) · `STYLES` (14) — bounce, hype, clean · `HOOK` (22) · `FONT_FILES` (24) · `CAP_MAX_W` (25) · `CAPTION_LEAD` (72) · `LAYOUTS` (81) — blur, zoom, crop, gameplay, blurcam
- `_Font` (28) · `install_fonts` (73) · `_ts` (86) · `_clean` (92) · `_key` (96) · `_groups` (100)
- `geometry` (113) · `_hook_events` (129) · `CONTEXT_SECONDS` (161) · `_extra_events` (164) · **`build_ass` (185)**
- `PIP_W` (259) · `PIP_MARGIN` (260) · **`_filter(layout, fg_h, facecam)` (263)** — ffmpeg filter graph per layout
- `_hook_y` (295) · `_hook_y_cam` (303) · `_qsv_ok` (309) · `RENDER_SECONDS` (310)
- **`render_clip(...)` (313)** — writes `.mp4`, `.jpg`, `.ass` via a short temp folder · `_render_in` (340) — NVENC → QSV → x264

#### studio/facecam.py
Finds the webcam box in a gaming stream from its straight, still border; an optional AI guess is checked against measurements.
- Tuning constants (34–45): `W`, `H`, `MAX_FRAMES`, `MIN_SIZE`, `MAX_SIZE`, `ASPECT_MIN/MAX`, `STILL_*`, `EDGE_FLUSH`, `MATCH`, `EDGE`
- `_frames` (48) · `_duration` (68) · `_profiles` (78) · `_peaks` (90) · `_size` (102) · `_stillness` (121)
- `_plausible` (130) · `_local` (157) · `_overlap` (186) · `_full_frame` (198) · `_best` (215) · `_snap` (222) · `_corner` (247) · `_finish` (267)
- `_frame_jpeg` (284) · `_asked` (296) · `_seen` (308)
- **`detect(path, ask)` (329)** — returns `{x, y, w, h, corner, score, conf}` or None

#### studio/quality.py
Finds ad breaks and frozen "be right back" screens from a frame-difference motion map.
- `motion_map` (32) · `static_ranges` (69) · `static_overlap` (91) — whole file, or one clip's seconds (`jobs._is_static`)

#### studio/roman.py
Hindi, Urdu, Cyrillic, Greek and Korean caption text into Roman letters (fallback when the AI doesn't).
- `DEVANAGARI` (29) · `OTHER_SCRIPT` (30) · `MORE_SCRIPTS` (50) · `_WORDS` (23) · `_UR_WORDS` (149)
- `has_hindi` (33) · `needs_roman` (37) · `drawable` (44) · `_letters` (66) · `_korean` (81) · `_word` (89) · `_urdu_word` (170)
- `to_roman(text)` (240) · `unicodedata_nfc` (256) · `words(ws)` (261)

#### studio/gpu.py
Whether the NVIDIA card is used for encoding (NVENC) and speech (CUDA); each checked first, settings in `hardware.json`.
- `init` (28) · `prefs` (33) · `save` (41) · `_run` (50) · `card()` (55) · `nvenc()` (72)
- `_sherpa_version` (107) · `nvidia_dirs` (114) · `_has_dll` (131) · `speech()` (140) · `speech_failed` (174) · `recheck` (180)
- `use_nvenc()` (185) · `speech_on_card()` (190) · `status()` (195)

#### studio/fetch_model.py
Downloads the ~480 MB speech model on first need. `python -m studio.fetch_model`.
- `URL` (13) · `ready()` (18) · `_progress` (26) · `ensure()` (31) · `main()` (67)

### AI, live and posting

#### studio/brain.py
Picks clip-worthy moments and writes their text. Builds prompts, asks the AI via `ai.py`, cleans every answer. Also caption fixes and translation. Video text is untrusted: in through `_safe`, out through `_text`.
- Prompts: `SCHEMA` (14) · `HEAD` (38) · `RULES` (56) · `GAME_RULES` (101) · `GENERIC_TAGS` (112)
- Cleaning: `_safe` (117) · `_text` (122) · `_num` (128) · `_fmt` (136) · `_tidy` (141) · `_same_word` (173) · `_overlaps` (179)
- `make_lines` (183) — lines with (LOUD)/(SPIKE)/(CHAT) marks · `loud_zscore` (207) · `loud_jumps` · `_reaction` · `LEAD_IN` · `ask_ai(prompt, schema, purpose)` (213) — tries each model with retries
- `sentence_ends` (236) · `_snap` (248) · `fallback_by_loudness` (275) · `_game_rules` (294)
- **`find_clips(...)` (303)** — whole video, 15-minute windows · `find_live_clips` (347)
- `describe` (366) — hook/title/post text for a hand-cut clip · `look_for_facecam(jpeg)` (423)
- `judge_transcript` (464) · `judge_signals` (484) — the two live judges
- `needs_translation` (515) · `_spread` (521) · `translate_caption_words` (530) · `english_captions` (553) · `fix_caption_words` (573) · `_fix_caption_words` (580)

#### studio/ai.py
The only code that talks to an AI service. Bring-your-own key; settings in `ai.json` (dashboard) or `.env`.
- **`PROVIDERS` (25)** — add a provider here · `ALIASES` (35) · `NO_KEY` (36)
- `_file` (43) · `_from_dashboard` (47) · `current()` (63) · `provider` (73) · `models` (77) · `key` (81) · `label` (85) · `base_url` (89)
- `ready()` (94) · `public()` (99) · `save(...)` (110) · `list_models` (145) · `test()` (173)
- `AIError` (182) · `explain(e)` (189) · `note_problem` (204) · `clear_problem` (211) · `_fail` (215)
- `_json_schema` (221) · `_wrapped` (230) · `_json_chunks` (235) · `_parse` (263)
- **`call(model, prompt, schema, timeout)` (295)** — returns `(json, tokens_in, tokens_out)` · `see(prompt, image)` (304)
- Per-service: `_gemini` (353) · `_openai_body` (366) · `_from_events` (389) · `_openai` (417) · `_anthropic` (434)

#### studio/usage.py
One row per AI call; builds the AI usage page. Nothing is charged or limited.
- `set_context` (17) · `record` (22) · `forget` (35) · `forget_all` (39) · `brief()` (52) · `summary` (70)

#### studio/live.py
Records live streams into a rolling buffer, transcribes, watches loudness and chat, asks the AI for clips, renders them. Each recording is a `Session` in `SESSIONS`; a watcher auto-starts recordings.
- `NotLive` (29) · `_trim_names` (33) · `media_safe` (45) · `normalize(url)` (50) · `_Quiet` (58) · `resolve(url)` (65)
- `active` (89) · `active_mine` (93) · `active_for(cid)` (98) · `mine(jid)` (102)
- **`class Session` (108)**:
  - `_ask_ai` (161) · `_find_facecam` (181) · `_game` (198) · `start` (215) · `stop` (223)
  - Recording: `_ingest` (235) · `_ingest_loop` (245) · `_scan_segments` (297)
  - Chat: `_chat` (318) · `_chat_spike` (355) · `chat_people` (375)
  - `_transcribe_step` (383) · `_watch_spikes` (411) · `_ai_check` (447) · `_verdict` (525) · `_triggers` (532) — "clip that"
  - `_manual_step` (554) · `_add_clip` (572) · `_render` (581) · `_align` (626) · `clip_last(seconds)` (652)
  - `_publish` (658) · **`_analyze` (675)** — main loop
- `recover(job)` (740) · `start_session(creator, url)` (779) · `_watch_user` (806) · `check_now(cid)` (820) · `_watch_one` (837)
- `watch_loop` (868) · `_resume_recordings` (883) · `start()` (908)

#### studio/creators.py
Each user's creator workspaces (`users/<user>/creators/<id>`), their settings and activity log.
- `_root` (12) · `DEFAULTS` (17) · `PLATFORMS` (25) · `platform_key` (28) · `_fix` (34) · `NUMERIC` (45) · `root(cid)` (49) · `_clean` (55)
- `_mine` (95) · `forget` (111) · `all_creators` (117) · `get` (121) · `_write` (128) · `create` (140) · `update` (154)
- `set_profiles` (171) · `log` (191) · `read_log` (210)

#### studio/profiles.py
Public profile (name, picture, followers) and live status of creators' channels. Best effort, cached and shared across users.
- `UA` (16) · `PIC_HOSTS` (18) · `MAX_PIC` (19) · `_pool` (23) · `LIVE_SHARED_FOR` (26)
- `_get` (35) · `_meta` (41) · `_picture` (46) · `_short` (58) · `platform_of` (66) · `fetch` (71) · `_fetch` (90) · `preview` (128)
- `_twitch_live` (145) · `_twitch_profile` (167) · `_ydl_info` (189) · `_no_date` (198)
- `live_now` (203) · `live_shared` (258) · `_clean_name` (287) · `_profiles` (293) · `refresh` (318) · `needs_refresh` (363)

#### studio/posting.py
Post queue: when each clip goes to which account, per-platform text and tags, background posting, view tracking (`posts.json`).
- `_mine` (19) · `_save` (25) · `forget` (32) · `_mirror` (46) · `_next_slot` (55) · `enqueue` (67) · `on_clip_ready` (91)
- `pick_tags` (106) · `_credit` (116) · `package(clip, creator, platform, job)` (131) · `_caption` (148)
- `_post(p)` (153) · `_run()` (188) — posting loop · `_stats_for` (206) · `_stats` (222)
- `cancel` (234) · `retry` (244) · `overview` (254) · `digest_text` (294) · `start()` (307)

#### studio/games.py
Which game a stream is about, from its title; returns that game's post tags. A hint for copy only.
- `GAMES` (21) · `MOMENTS` / `moments_of` — what to look for in a game · `GENERIC` (50) · `_ALIASES` (53) · `_norm` (61) · `detect(*texts)` (65) · `name_of` (78) · `tags_of` (89)

### Settings, setup and support

#### studio/config.py
Every setting, from env vars or `.env`; decides the data folder and reads secrets from `*_FILE` files.
- Loading: `_load_dotenv` (11) · `_keep` (29) · `_secret` (38) · `_read_secret` (43)
- Folders (54+): `STORAGE_FILE` (57) · `_move_folder` (60) · `_data_folder` (97, `PEAKCUT_DATA`) · `USERS_DIR` (120) · `MODELS_DIR` (121) · `TMP_DIR` (122) · `FONTS_DIR` (123) · `DATABASE_URL` (138) · `user_dir(uid)` (154)
- Video and speech: `YT_COOKIES_BROWSER` (128) · `YT_COOKIES_FILE` (129) · `YT_TRANSCRIPT` (130) · `ASR_MODEL_NAME` (136) · `SKIP_STATIC` (143) · `STATIC_THRESHOLD` (144) · `STATIC_MIN_SECONDS` (145) · `LIVE_AI_TIMEOUT` (148)
- Site (160+): `HOST` (161) · `PORT` (162) · `PUBLIC_URL` (163) · `HTTPS` (164) · `SESSION_DAYS` (165) · `ACCOUNTS` (169) · `REPO_URL` (172)
- Limits (175+): `MAX_UPLOAD_MB` (186) · `UPLOAD_PART_MB` (189) · `JOB_WORKERS` (191) · `MAX_ACTIVE_JOBS_PER_USER` (192) · `MAX_LIVE_TOTAL` (193) · `MAX_LIVE_PER_USER` (194) · `MAX_VIDEO_HOURS` (195) · `MAX_LIVE_HOURS` (196) · `MAX_USER_GB` (197) · `MAX_CREATORS` (198) · `ALLOWED_SITES` (199)
- AI (202+): `AI_PROVIDER` (204) · `AI_MODELS` (205) · `AI_BASE_URL` (206) · `ai_key()` (209) · `ai_ready()` (213)
- Email (218+): `SMTP_*` (219–221) · `MAIL_FROM` (222) · `VERIFY_EMAIL` (227) · `smtp_password()` (230)
- Google (234+): `google_client()` (235) · Video: `MAX_SOURCE_HEIGHT` (255)

#### studio/storage.py
The one data folder: space used/free, open it, move it (takes effect next start).
- `_size` (20) · `used_bytes` (31) · `drive_of` (38) · `full_message` (43) · `shutil_free` (54) · `pending` (59) · `info` (69) · `open_folder` (83) · `pick_folder` (98) · `change` (109) · `cancel_change` (145)

#### studio/tools.py
Finds ffmpeg/ffprobe and explains in plain words when they're missing.
- `NEEDED` (13) · `HELP` (14) · `_places` (21) · `setup()` (48) · `missing()` (68) · `explain(e)` (76)

#### studio/checklist.py
What still needs setting up by hand (ffmpeg, AI key, YouTube cookies, apps, graphics card, sign-in).
- `_ffmpeg` (19) · `_ai` (27) · `_cookies` (36) · `_apps` (61) · `_card` (70) · `_signin` (83) · `_safe` (100) · `items()` (108) · `todo()` (119)

#### studio/load.py
Samples CPU, RAM and disk each second; new heavy work waits while the machine is nearly full.
- `BUSY_CPU` (13) · `MIN_FREE_RAM_GB` (14) · `MIN_FREE_DISK_GB` (15) · `_cpu_times` (23) · `_ram_free_gb` (38) · `_watch` (56) · `start` (85) · `busy()` (93) · `disk_full()` (101) · `state()` (106)

#### studio/updates.py
Checks GitHub once a minute for a newer commit and shows a dashboard notice.
- `REPO`/`BRANCH`/`ON`/`EVERY` (20–23) · `current()` (30) · `newest()` (57) · `_what_changed` (66) · `check` (81) · `latest()` (115) · `start()` (120)

#### studio/notices.py
In-app bell notifications (newest 100 per person).
- `KEEP` (11) · `add(uid, kind, title, …)` (15) · `mine` (39) · `unread` (49) · `read_all` (62)

#### studio/alerts.py
Phone alerts via Discord webhook and/or Telegram; never blocks recording or posting.
- `configured` (12) · `send(text)` (17) · `notify(text, kind, link)` (39) · `digest_loop` (52) · `keep_awake_loop` (67) — stops Windows sleeping while busy

#### studio/mailer.py
Account emails over SMTP with a branded layout; without SMTP the link goes to the log.
- `ready` (20) · `_html` (28) · `preview` (63) · `send` (71)

#### studio/feedback.py
User bug reports and ideas, listed for admins.
- `KINDS` (8) · `STATUSES` (9) · `Refused` (12) · `submit` (16) · `listing` (36) · `set_status` (50)

#### studio/safe.py
- `friendly(e, limit)` (7) — error text safe to show users (server paths replaced, missing ffmpeg explained)

#### studio/fonts/
Bundled caption fonts (Anton, Archivo Black, Poppins ExtraBold) and their OFL licences.

---

## web/ — pages

#### web/index.html
The whole signed-in app (plain JS, no build). Renders views, polls `/api/sync`, and handles clicks through one delegated handler switching on `data-act` (around lines 2400–2570).
- **Core:** `api` (917) — fetch wrapper, 401 → /login · `send` (923) · `toast` (924) · `put` (931) · `ask` (932) · `startTour` (942)
- **Render loop:** `render` (2252) · `tick` (2258) — `/api/sync` poll · `loop` (2291) · `drawShell` (1257) · `pathFor` (1315) · `fromPath` (1320) · `remember` (1328) · `go` (1333) · `setTab` (1356)
- **Creators and live:** `creatorId` (1066) · `creator` (1067) · `aiCard` (1071) · `avatarUrl` (1089) · `playerSrc` (1091) · `drawStream` (1099) · `liveOn` (1126)
- **Chrome:** `statusBadge` (1127) · `meAvatar` (1138) · `closePops` (1146) · `openPop` (1148) · `openBell` (1156) · `markRead` (1170) · `openAcct` (1171) · `chime` (1185) · `noticeToast` (1198) · `checkNew` (1211) · `openFeedback` (1223) · `updateHow` (1229) · `greeting` (1242) · `moveInd` (1245)
- **Link/file composer:** `drawAdd` (1368) · `picker` (1406) · `stepper` (1413) · `choice` (1419) · `targetCreator` (1452) · `jobOptions` (1453) · `att` (1465) · `attach` (1476) · `canGo` (1489) · `drawAtt` (1498) · `lookUp` (1543) — `/api/preview` · `takeLink` (1554) · `onLink` (1570) · `sendBig` (1594) — chunked upload · `sendFile` (1633) · `loadPicked` (1652) · `clipSelected` (1660) · `makeClips` (1674)
- **Job list:** `scoreCls` (1715) · `postPills` (1716) · `clipHtml` (1723) · `spark` (1746) · `everyPick` (1748) · `liveHtml` (1754) · `jobHtml` (1774) · `selParts` (1794) · `selClips` (1799) · `drawSelBar` (1805) · `zipDownload` (1823) · `askTyped` (1829) · `drawJobs` (1840)
- **Creator setup:** `costHint` (1865) · `channelRows` (1869) · `saveChannels` (1883) · `drawCreatorForm` (1888) · `creatorForm` (1929) · `saveCreator` (1931)
- **Overview, usage, log:** `drawLog` (1935) · `loadOverview` (1942) · `barChart` (1943) · `nextSteps` (1961) · `drawOverview` (1970) · `loadUsage` (2005) · `tokenChart` (2010) · `hbars` (2024) · `drawUsage` (2029)
- **Settings:** `setTabs` (2051) · `aiHints` (2057) · `drawSettings` (2066) — AI, hardware, storage, apps, setup, plans · `saveSettings` (2204)
- **Clip editor:** `openClip` (2207) · `drawClipDlg` (2208) · `syncCaptionStyle` (2304)

#### web/admin.html
Admin console: stats, feedback inbox, user drawer (disable, enable, delete). Calls `/api/admin/*`, `/api/auth/me`, `/api/auth/logout`.

#### web/auth.html
Sign in / sign up, with Google when configured. Calls `/api/public`, `/api/auth/login`, `/api/auth/signup`, `/auth/google/start`.

#### web/reset.html
Forgot / reset password. Calls `/api/auth/forgot`, `/api/auth/reset`.

#### web/landing.html
Public marketing home page. Calls `/api/auth/me` only.

#### web/legal.html
Terms and privacy template; the server fills `{{TITLE}}` and similar placeholders.

#### web/ascii.js, web/gradient-ascii.js
Decorative canvas backgrounds: `PeakAscii(canvas, opts)` and `GradientASCII(host, props)` (returns `stop()`).

#### web/brand/
Demo clips and posters (`demo-bounce`, `demo-clean`, `demo-hype`), `favicon.svg`, `logo.svg`, `logo-light.svg`, `logo-email.png`.

---

## tests/

`python tests/run.py` starts a throwaway server on port 8799 (`PEAKCUT_TEST_PORT`) with a temp data folder and AI, email, Google and update checks off, runs every test file as a subprocess, counts `PASS` lines and prints `FAIL` lines. Real data is never touched.

| File | Covers |
|---|---|
| `test_permissions.py` | sign-up can't grant admin; users can't see each other's data; disabling takes effect at once |
| `test_abuse.py` | body size limits, unverified accounts, caching headers, address spoofing, throttles |
| `test_load_queue.py` | the job line holds when full and moves when free |
| `test_delete.py` | deleting clips, videos, creators, accounts; bulk; zip |
| `test_upload_parts.py` | chunked uploads assemble correctly and can't be misused |
| `test_ai.py` | AI calls with network stubbed; per-user usage |
| `test_local.py` | default no-sign-in mode, AI key from dashboard, model lookup |
| `test_checklist.py` | setup checklist, YouTube cookies |
| `test_roman.py` | Hindi/Urdu captions in Roman letters |
| `test_captions.py` | caption preferences and subtitle events |
| `test_connect.py` | Connect and posting for YouTube, Instagram, TikTok with stand-in platforms |
| `test_updates.py` | "new version" notice |
| `test_limits.py` | no limits by default |
| `test_stuck.py` | overlapping captions, hanging clips, sentence-end endings |
| `test_static.py` | ad breaks and frozen screens |
| `test_answer.py` | malformed AI answers |
| `test_games.py` | game detection and tags |
| `test_facecam.py` | webcam detection and render layout |
| `test_tools.py` | fresh-install errors (no ffmpeg, no model, AI errors) |
| `test_storage.py` | storage page, full drive, moving the folder |
| `test_hardening.py` | rate limits, email rules, Google sign-in, prompt injection |
| `test_robustness.py` | activity log size, machine monitor, failed recordings, admin totals |

---

## Deploy and docs

| File | What it is |
|---|---|
| `Dockerfile` | python:3.11-slim + ffmpeg, Noto fonts, deno; runs `python -m studio.server` on 8765 |
| `docker-compose.yml` | Postgres 16 + app + Caddy (HTTPS); reads `.env` |
| `requirements.txt` | Python deps (fastapi, uvicorn, SQLAlchemy, psycopg, sherpa-onnx, yt-dlp, pillow, …) |
| `.env.example` | every setting, AI key first; copy to `.env` |
| `deploy/Caddyfile` | automatic HTTPS, 2200 MB upload limit |
| `deploy/Caddyfile.origin` | Caddy with a Cloudflare origin certificate |
| `deploy/docker-compose.traefik.yml` | override for an existing Traefik server |
| `deploy/nginx-peakcut.conf` | nginx site config for a shared server |
| `deploy/gpu/` | GPU image and compose |
| `README.md` | product overview, features, install |
| `DEPLOY.md` | server setup guide |
| `GAMING.md` | gaming mode: game detection, facecam, gaming rules |
| `AGENTS.md` | contributor and AI-assistant guide: run, test, house rules |
| `CLAUDE.md` | behaviour guidelines for Claude |
