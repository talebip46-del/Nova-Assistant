# 🗺️ نقشه‌ی کامل پروژه — Nova Assistant (شناخت مرجع برای توسعه‌های بعدی)

> این سند حاصل یک ممیزی کامل در دور v8.2.1 است و **حافظه‌ی مرجع** همه‌ی جلسات
> بعدی کار روی این پروژه است: معماری، قراردادها، اسرارِ پوشه‌ی `.nova`، سنتِ
> انتشار، و فهرست چیزهایی که عمداً دست نخورده‌اند. هر تغییر بعدی باید این
> سند را هم به‌روز کند.

## ۱) هویت پروژه در یک نگاه

- **Nova Assistant** = دستیار AI محلی (فارسی-محور) + ایجنت کدنویسی «Nova Code». هسته **۱۰۰٪ کتابخانه‌ی استاندارد پایتون، صفر وابستگی** — روی لپ‌تاپ ضعیف هم می‌چرخد.
- **دو چهره، یک ایجنت**: ترمینال (`app/nova` / `app/novacode`) و وب PWA (`app/nova --web` → `web_server.py` + `web/index.html`).
- **مغز قابل تعویض**: Ollama خودکار، فایل GGUF با llama-server، ۳۰ ارائه‌دهنده‌ی ابری + custom (OpenAI/Anthropic/Gemini-wire).
- نسخه‌ی فعلی: **8.12.0** (`nova.VERSION` + `nova_think.VERSION`)، کدنیم «master switch» — دور تضمین صفر تا صد: ممیزی سه‌رشته‌ای موازی + بازتولید اجرایی هر یافته؛ ۱۳ مشکل اثبات‌شده و رفع‌شده (کلیدِ اصلیِ نگهبان روی مسیر وبِ تأیید و گیتِ حدسی، گیتِ deep مستقل از wiring، ربایشِ پیش‌نمایشِ دستورهای مولد، صداقتِ ورودیِ `/api/settings`، پیمایشِ هرس‌شده، مهلتِ nان-پسند، پرچمِ تازه‌ی `batch_refused`)، هر کدام با تست رگرسیون دائمی (FIXES-8.12.0). لایه‌های طراحی v8.9+v8.10 و همه‌ی قراردادهای قبلی دست‌نخورده.
- مقیاس: `nova.py` ≈ ۱۳٬۴۰۰ سطر | `web/index.html` ≈ ۴٬۵۰۰ سطر | `web_server.py` ≈ ۲٬۷۵۰ سطر | ۷۰+ ماژول `nova_*.py` | **۲۴۰۵ تست** در ۶۳ فایل.

## ۲) نقشه‌ی درخت

```
project/
├─ README.md               # سند اصلی محصول (تاریخچه: فقط نسخه‌ی ۸.۱۲.۰)
├─ FIXES-6.2.1 … 8.12.0.fa.md # ۳۶ سند تعمیر — هر نسخه یک گزارش کامل
├─ PROJECT-MAP.fa.md          # همین سند
└─ app/
   ├─ nova.py                 # هسته ایجنت (Session، خط لوله چت، ۱۰۳ دستور)
   ├─ nova_assistant.py       # دروازه CLI ماژول‌محور (voice/photo/pixel/…)
   ├─ novacode_entry.py       # روتر exe کنسولی (PyInstaller)
   ├─ exe_entry.py            # روتر exe گرافیکی (بدون آرگومان = serve)
   ├─ web_server.py           # سرور وب (ThreadingHTTPServer + NDJSON استریم)
   ├─ web/index.html          # UI تک‌فایلی PWA (CSS + JS داخلی، RTL)
   ├─ nova_think.py           # پروتکل THINK و نجات بلوک باز (v8.2)
   ├─ nova_ctxengine.py       # موتور کانتکست: سقف لوکال/ابری + دیجست (v8.3)
   ├─ nova_guardian.py        # نگهبان کد: ناظر + ~۳۰ زیرایجنت زبانی + وب‌سرچ اختصاصی (v8.4)
   ├─ nova_probe.py           # شکارچی باگ: سیم‌کشی مرده + سوئیپ عمیق (v8.6) + دودتست + مرورگر + تکمیل‌بودن
   ├─ nova_vision.py          # لایه بینایی: تشخیص خودکار vision + گیت تأیید عکس (v8.6)
   ├─ nova_providers.py       # لایه سیم مغزها (۴ پروتکل سیم + گاوصندوق کلید)
   ├─ nova_search.py          # پژوهش وب بی‌کلید (DDG/Wikipedia/SO + ۳۸۹ دامنه معتبر)
   ├─ nova_localmodels.py     # کشف GGUF + اجرای llama-server (تک‌سرور)
   ├─ nova_intel.py           # هوش پروژه (اسکن/گراف وظیفه/حافظه معنایی/حلقه عامل/منتقد)
   ├─ nova_images.py          # موتور عکس واقعی (جستجو/دانلود/پرکردن HTML)
   ├─ nova_design.py|style.py|fonts.py  # موتور زیبایی + منوی شش‌لایه‌ی اختیاری (v8.9+v8.10) + پروفایل سبک + ۶۶ فونت آفلاین
   ├─ nova_atomic.py          # نوشتن اتمیک + قرنطینه + قفل فرآاینجا
   ├─ nova_snapshots.py       # یونیت‌های undo + چک‌پوینت دستی
   ├─ nova_security.py        # پرده‌ی فرمان‌های مخرب + RateLimiter (وب هدرها در web_server)
   ├─ nova_secretbox.py       # رمزنگاری at-rest (فقط حافظه چت؛ گاوصندوق‌ها chmod600)
   ├─ nova_iran_services.py   # ۲۰ سرویس ایرانی (کاوه‌نگار/زرین‌پال/نشان/نوبیتکس/بله/آپارات…)
   ├─ nova_sandbox.py|rlimits.py|policy.py|plugins.py  # سندباکس فایل/فرمان، سقف منابع، پلاگین
   ├─ nova_bg.py|council.py|subagent.py|explore.py|router.py|economy.py|cost.py  # پس‌زمینه/شورا/ایجنت‌های موازی/کشف بهترین/روتر دشواری/اقتصاد
   ├─ nova_modules/           # voice/photo/pixel/flow/knowledge/assign (لایه ماژول)
   ├─ fonts/                  # ۶۶ فونت woff2 (۳۲ فارسی) + index.json + مجوزها
   ├─ tests/                  # ۶۳ فایل، ۲۴۰۵ تست unittest (پین‌محور + درایور واقعی سرور)
   └─ scripts/                # package_vXXX.py، pin_vXXX.py، live_test_vXXX.py، smoke
```

## ۳) خط لوله‌ی چت (قلب ایجنت) — زنجیره‌ی دقیق

```
dispatch(sess,line) → chat_turn → sess.compose → sess.build_messages
  [گام صفر v8.3: دیجست موتور کانتکست اگر تاریخچه از بودجه رد شود]
  → sess._prompt_ctx (بودجه: سقف لوکال/ابریِ موتور کانتکست)
  → stream_chat → providers.resolve_route("coding") → سیم HTTP/SSE
    [v8.3: payload Ollama همیشه num_ctx = سقفِ لوکالِ کاربر — قانون نوا]
  → [v8.2] think.extract → نجات بلوک باز (salvaged) + complete صادق
  → [v8.2] ادامه‌ی خودکار ≤۲ دور (NOVA_AUTO_CONTINUE؛ _resume_message با دمِ خام در آخر)
  → parse_files/parse_edits (FILE_RE سطر-لنگر) → یک دور تعمیر پروتکل (بلاک بی‌نام)
  → حلقه‌ی ابزار ≤۳ دور [SEARCH:]/[READ:]/[IMG:]
  → offer_apply (سندباکس فایل → گیت لینت → ★گیت ناوگان v8.4 (قطعی؛ رد = هیچ بایت + repair تزریقی)
     → تراکنش اتمیک+ژورنال → بکاپ
     → هوک‌های design/images/fonts → snapshot یونیت → گیت خودکار git/تاریخ
     → گیت feedback (تست/لینت + ★بازبینی موازی ناوگان v8.4 روی مغز لوکال)
     → گیت intel (تاثیر/منتقد/پسرفت/حافظه/آینه‌ی داشبورد))
  → Run hint (خط آخر خارج از بلوک‌ها) → run_command
[پس از هر دور v8.3: sess._maybe_ctx_compact — دیجست اگر از آستانه رد شده باشد]
```
حلقه‌های بالاتر: `auto_build` (≤۱۲ گام)، `fix_flow`، `verify_flow` (≤۸ گام)، `/loop` اینتِل‌دار.

**پروتکل‌های متنی**: `=== FILE: path === … === END ===`، `=== EDIT: path ===` با hunk‌های `<<<<<<< SEARCH/=======/>>>>>>> REPLACE`، `=== PLAN ===`، `=== THINK === … === END ===`، `Run:`/`Preview:`، توکن ابزار فقط تنها روی یک سطر.

## ۴) رجیستری دستورها — ۱۰۴ فرمان + ۴ اسم مستعار

`/workspace(/cd) /ls /read /load /search /learn /docs /kb /img /imgdl /fonts
/model(/models) /provider /key /services /catalog /brain /think /custom /saver
/disk /mode /run /fix /verify /check /serve /auto /autofix /init /compact /retry /review
/changes /timeout /undo /snapshot /snapshots /restore /map /explain /policy
/secure /doctor /hw /timeline /explore /rag /style /route /gitlog /graph
/symbols /patch /writedocs /coverage /selftest /agent /bench /lock /sandbox
/limit /log /blackbox /plugin /novaignore /todo /skill /autotest /cost /estimate
/bg /council /pr /memory /profile /rescan /clear /voice /stt /photo /pixel /flow
/knowledge /platforms /assign /status /export /help /intel /tasks /mem /ctx
/ctxset /impact /regress /gentests /critic /workspaces /loop /guardian /probe
/vision /quit(/exit|/bye)`

- ثبت در `TOOLS` (سطر ~۱۰۳۴۱ nova.py) → `TOOL_INDEX` با **خطای متوقف‌کننده روی نام تکراری**.
- `/help` و تب راهنمای وب از همین رجیستری می‌خوانند؛ وب برای وضعیت، مستقیم توابع `nova.web_*` را صدا می‌زند (نه رشته‌ی دستور).

## ۵) مدل وضعیت `.nova/` (به‌ازای هر ورک‌اسپیس)

| فایل | نویسنده | نقش |
|---|---|---|
| memory.json(.enc) | nova_memory | حافظه چت (قابل رمز با /lock) |
| profile.json / policy.json / sandbox.json / security.json(+audit.jsonl) | project/policy/sandbox/security | پیکربندی‌های هر پروژه |
| providers.json / iran_services.json / platforms.json | providers/iran/platforms | گاوصندوق کلید (chmod600، اتمیک، قفل فایل) |
| snapshots/auto|manual/<id>/ + history.git/ | snapshots/commitmsg | undo بی‌نهایت + کامیت هر اعمال |
| logs/nova.log + logs/flightlog.ndjson | log/flightlog | خطاها + جعبه سیاه تصمیم‌ها |
| intel.json، tasks.json، memory_vec.json، agent_status.json، agent_runs/، regression.json | intel | هوش پروژه |
| skills.json، think.json، talk_web.json، style.json، rag_index.json، bench.json، route.json، responses_cache.json، costs.json، pricing.json، doctor.json، local_models.json، context.json (v8.3: سقف‌های کانتکست)، guardian.json (v8.4: کلیدهای نگهبان)، probe.json (v8.5: کلیدهای شکارچی باگ)، .nova/images.json | متفرقه | حالت‌های فیچرها |
| بیرون `.nova`: NOVA.md، .novaignore، .nova_knowledge.md، .nova_backups/، assets/images/ | — | قانون پروژه/نمای مسدود/KB/بکاپ‌ها/عکس‌ها |

رجیستری چندپروژه‌ای: `~/.nova/workspaces.json` (قابل تغییر با `NOVA_HOME`). تست‌ها ایزوله می‌کنند با ورک‌اسپیس موقت + این env.

## ۶) چهره‌ی وب — قراردادهای کلیدی

- **استریم = NDJSON chunked** روی HTTP/1.1 (نه SSE): رخدادهای `note|tok|done|err|web|webmode|think|todo|notify…` با `_emit` زیر قفل؛ پایان با `0\r\n\r\n`.
- زنجیره‌ی امنیتی: throttle → rate-limit → same-origin → JSON-only POST → Host-guard → کوکی توکن (compare_digest). هدرها: nosniff، DENY فریم، no-referrer، CSP.
- تب‌ها: کدنویسی (پیش‌فرض) | گفت‌وگو (جستجوی وب خودکار/همیشه/خاموش) | دانش | مدل‌ها | وضعیت | هوش | راهنما. voice/photo/pixel/flow **غیرفعال پیش‌فرض** (`NOVA_DISABLED_MODULES`) — سه لایه‌ی قطع (دکمه‌ی disabled، DISABLED_VIEWS، 403 سرور).
- `splitThink` سمت مرورگر همان قانون نجاتِ سرور را اجرا می‌کند (workRe/salvage).
- `/serve` (پیش‌نمایش سایت) از nova.py است — سرور مستقل روی 127.0.0.1:8000 با گارد dotfile/symlink.

## ۷) سنت انتشار (release discipline) — برای هر تغییر آینده

1. **فیلد نسخه**: `nova.VERSION` + `nova_think.VERSION` (فقط این دو منبع حقیقت‌اند).
2. **پین‌ها**: `scripts/pin_vXXX.py` می‌سازیم و می‌چرخانیم (۸.۲.۱: ۳۲ پین در ۲۷ فایل تست). تست‌ها `assertEqual(nova.VERSION, …)` دارند.
3. **سند تعمیر**: `FIXES-x.y.z.fa.md` در ریشه (ریشه‌یابی با شواهد → تعمیرها → تست‌ها → بسته‌بندی).
4. **بخش README**: بالای فایل، بعد از مقدمه.
5. **تست جدید**: `tests/test_vXXX_*.py` به سبک پین (source-assertion) + درایور واقعی وقتی لازم است. سبک: unittest، آفلاین، network با stub.
6. **بسته‌بند**: `scripts/package_vXXX.py` (الگوی v821) — ۷ پروب شامل اجرای **کل مجموعه داخل بسته‌بندی**، مقایسه با zip قبلی (حذف عمدی = لیست سفید `DROPPED_ON_PURPOSE`)، هویت بایتی ×۲. خروجی: `<repo>/download/` یا `NOVA_OUT_DIR`.
7. قبل از اتمام: `py_compile` همه، اجرای کامل pytest، به‌روزرسانی PROJECT-MAP و worklog.

## ۸) تصمیم‌های ثبت‌شده‌ی این دور (تا دوباره بحث نشوند)

- **قوانین ناوگان نگهبان (v8.4)**: ① دروازه‌ی pre-apply فقط قطعی است (صفر call مدل) — فقط او حق «رد» دارد ② بازبینی مدلی فقط روی مغز لوکال (`_coding_brain_is_local`) — مغز ابری هرگز call ناوگان نمی‌گیرد (کردیت نمی‌سوزد) ③ یافته‌های زیرایجنت‌ها همیشه «هشدار»اند، هرگز رد ④ generic/markdown رد نمی‌کنند، باینری از فیلتر رد می‌شود ⑤ وب‌سرچ ناوگان بودجه‌ی سخت دارد و ok=False همیشه یعنی دانش‌نامه‌ی داخلی (نه خطا) ⑥ تست‌های «شمارش-کال» ناوگان را با `NOVA_GUARDIAN=0` پارک می‌کنند (الگوی v750/v820) — تست نگهبان جدید جدا می‌نویسیم.

- **«رشته‌های خراب `[m`» واهی بودند**: ترمینال این محیط دنباله‌ی `[m` را از خروجی می‌خورد (`[model]` → `odel]` نمایش می‌داد). همه با AST/نمای بی‌خطر سالم اثبات شدند. **قانون: هر «خرابی رشته‌ی» مشکوک را قبل از ویرایش با جایگزینی براکت‌ها (⟦⟧) یا AST راستی‌آزمایی کن.**
- **۱۰ تابع/ثابت مرده عمداً ماندند**: `nova_secretbox.forget_key`+`_KEY_CACHE`، `nova_council.os_environ_get`، `nova_security.lockdown`، `nova_providers.registry_names`، `nova_subagent.concurrency_note`، `nova_sandbox.check_batch`، `nova_economy._reset_counters`، `nova_iran_services.CATEGORY_LABELS`، `nova_localmodels.GGUF_HEADER`، `nova_feedback.PY_ERR_RE`، ثابت‌های `nova_rlimits`/`nova_rag.DIM`/`nova_intel.LANG_BY_EXT`، `nova_bench.BenchError`. (حذف = ریسک import بیرونی؛ بی‌ضرر در فلسفه‌ی fail-soft.)
- **گاوصندوق کلیدها plaintext chmod600** می‌ماند (رمز at-rest فقط برای memory.json) — تصمیم فعلی محصول؛ اگر تهدید «سرقت دیسک» جدی شد، بحث secretbox برای providers.json.
- **`LAST_FINISH_REASON` گلوبال است** — مسابقه‌ی استریم‌های موازی (/explore) پذیرفته‌شده است (اثر: حداکثر یک دور ادامه‌ی اضافه/کم).
- **پیش‌فرض وبِ ناامن**: در حالت غیر secure، احکام confirm روی وب auto-allow می‌شوند — مستند است؛ اگر کاربر روی شبکه‌ی اشتراکی می‌گذارد، `/secure on` توصیه شود.
- **`ContextEngine` پیش‌فرض kb.json کهنه دارد** — فراخوان‌های واقعی مسیر درست (`​.nova_knowledge.md`) می‌دهند؛ تغییر پیش‌فرض برای بعد.
- **`/api/explore` وجود ندارد** (فقط docstring در nova_explore) — فرمان ترمینالی هست؛ اگر خواستیم وبش کنیم، روت جدید در web_server.
- **اسکریپت fetch_fonts_v730.py نیست** (اشاره‌اش در سربرگ nova_fonts است) — فونت‌ها وندور شده‌اند؛ اشاره‌ی doc فقط کهنه است.

## ۹) نقاط داغ برای توسعه‌های بعدی (نقشه‌ی راه پیشنهادی)

1. **فعال‌سازی ماژول‌های voice/photo/pixel/flow در وب** — زیرساخت کامل است (API و UI نوشته شده، فقط kill-switch پیش‌فرض بسته است): `NOVA_DISABLED_MODULES=""` + رفع disabled دکمه‌ها + تست وب.
2. **پارتی ارسال تصویر در openai/anthropic** (gemini دارد) — پاریتی چندوجهی.
3. **رمزگذاری گاوصندوق کلیدها با secretbox** (اختیاری، passphrase محلی).
4. **subagent ها فایل می‌نویسند/اجرا می‌کنند؟** فعلاً فقط پیش‌نویس (نکته‌ی امنیتی v6.8) — اگر شد، سندباکس فایل و policy باید قاطی شوند.
5. **پنل اکسپلور در وب** (`/explore` ترمینالی هست؛ نتیجه در `result["explore"]` هم می‌آید — UI ندارد).
6. **پاکسازی نهایی dead code** پس از تصمیم کاربر (بند ۸).

## ۱۰) شگردهای کار روزمره روی این پروژه

- اجرای کل تست‌ها: `cd app && python3 -m pytest tests/ -q -p no:cacheprovider` (~۳ دقیقه؛ ۲۴۰۵ سبز).
- تست سریع یک فایل: `python3 -m pytest tests/test_v821_audit.py -q`.
- چک سینتکس همه: `for f in *.py nova_modules/*.py; do python3 -m py_compile $f; done`.
- شروع وب: `python3 nova.py --web` (ورک‌اسپیس: `--workspace` یا env `NOVA_WORKSPACE`).
- بسته‌بندی: `NOVA_OUT_DIR=<dir> python3 scripts/package_v821.py` (zip قبلی را در همان dir با نام `nova_assistant_v8.2.0_fixed.zip` بگذار تا پروب مقایسه سبز شود).
- **هشدار آرتیفکت ترمینال**: خروجی ترمینال این محیط `[m` را می‌بلعد — برای رشته‌های مشکوک: `python3 -c "print(repr(...))"` با جایگزینی براکت، یا AST.
