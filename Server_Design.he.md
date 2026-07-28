# עיצוב שרת — הרחבת KFChess למשחק בזמן אמת בקנה מידה גלובלי

**בקצרה**: `server/main.py` כתהליך יחיד עובד עבור מאות משתמשים,
לא עבור 100 מיליון חשבונות רשומים או 10 מיליון שחקנים במקביל (§1). מסמך
זה מאמץ את הארכיטקטורה שהוצעה בקורס — API Gateway/WS Gateway,
Matchmaker, Game Allocator, Game Server Shards, NATS, PostgreSQL, Redis,
Docker/Kubernetes, Observability (§2–§4) — ולאחר מכן משתמש בה כדי לענות
על ארבע שאלות ההרחבה (scaling) של המטלה עם מספרים המבוססים על קוד
הבסיס הזה (§5–§8), בתוספת התאוששות מכשלים, נראות (observability),
ובדיקות היגיון של קיבולת (§9–§12).

**תוכן עניינים**

- §0 המודל שהשרת הנוכחי כבר פועל לפיו
- §1 מדוע תהליך אחד אינו מספיק
- §2 Docker / Kubernetes / K3s — תשתית ההרחבה
- §3 סקירת ארכיטקטורה
- §4 בעלות על חדרים: הפער שקיים בכל עיצוב המבוסס על רישום (registry) בלבד
- §5 שאלה 1 — מסד נתונים עבור 100 מיליון משתמשים רשומים
- §6 שאלה 2 — 10 מיליון שחקנים במקביל: פיזור וניתוב
- §7 שאלה 3 — תעבורת רשת: מה העלות של "מהלך כל 2 שניות"
- §8 שאלה 4 — משחקים של 30–90 שניות: המשמעות עבור תפקידי הקונטיינרים
- §9 מה קורה כאשר שרת נופל, ונראות (Observability)
- §10 האם הקיבולת באמת מסתכמת נכון?
- §11 סיכום תפקידים
- §12 שאלות פתוחות

## 0. המודל שהשרת הנוכחי כבר פועל לפיו

לפני עיצוב לצורך הרחבה (scale), כדאי לתת שם לתבנית שהקוד הקיים כבר
מממש, מכיוון שהמערכת המורחבת היא הרחבה של תבנית זו, לא תחליף לה:
`Bus` שבקובץ `events/bus.py` יחד עם `NetworkPublisher` שבקובץ
`server/publisher.py` כבר מהווים מערכת **publish/subscribe** מקומית —
`GameSession` מפרסם אירועי תחום (domain events) (מהלך התחיל, כלי הגיע,
לכידה התרחשה) אל האוטובוס (bus) שלו, ו-`_broadcast_to_game` שבקובץ
`server/game_loop.py` מפיץ כל אירוע לכל מנוי (subscriber) של אותו משחק
(שני המושבים, וכל שם משתמש צופה ב-`ActiveGame.spectator_usernames`).

זו בדיוק הצורה שמערכת מבוזרת זקוקה לה: **מפרסם (publisher) שלא יודע מי
מאזין, ומנויים (subscribers) שלא יודעים היכן חי המפרסם.** כל עיצוב
ההרחבה שלהלן הוא אותה תבנית עצמה, נמתחת על פני גבולות של תהליכים
ומכונות — לא מושג זר שהודבק לפרויקט.

## 1. מדוע תהליך אחד אינו מספיק

```
Clients → Game Server (single process) → SQLite
```

זה בדיוק מה ש-`server/main.py` מריץ כיום, וזה עובד — עבור מאות
משתמשים. הוא אינו יכול להגיע ל-100 מיליון חשבונות רשומים או 10 מיליון
שחקנים במקביל, משלוש סיבות קונקרטיות שנמצאות ישירות בקוד:

1. **`server/accounts_db.py`** פותח חיבור SQLite יחיד, המוגן על ידי
   `threading.RLock` יחיד. הנעילה הזו מסייעת בתוך תהליך אחד; היא לא
   עושה דבר ברגע שיש מאות קונטיינרים של Docker על מכונות שונות, מכיוון
   ש-SQLite הוא מסד נתונים מוטמע (embedded) בקובץ יחיד, ללא פרוטוקול
   client-server לגישת רשת מקבילית.
2. **`find_match`** שבקובץ `server/matchmaking.py` הוא סריקה מסוג
   O(n²) מעל `dict` בזיכרון. זה עובד עבור התור המקומי של תהליך אחד; אין
   לו דרך להתאים בין שני שחקנים שנקלעו לשני שרתים שונים.
3. **`_advance_game`** שבקובץ `server/game_loop.py` משדר תמונת מצב
   (snapshot) *מלאה* של הלוח בכל טיק — בתדירות של 20Hz
   (`DEFAULT_TICK_INTERVAL_S = 0.05`) — בין אם משהו זז ובין אם לא. זו
   העלות הדומיננטית בניתוח התעבורה שלהלן, וזה הדבר החשוב ביותר שהעיצוב
   הזה צריך לשנות, ולא רק לפזר.

## 2. Docker / Kubernetes / K3s — תשתית ההרחבה

**Docker** נותן לכל תפקיד (gateway, matchmaking, game-authority,
persistence) יחידת פריסה (deployment unit) אחת, עקבית וזהה:

```
Image → Docker 1, Docker 2, Docker 3, ... Docker N
```

כל עותק מתנהג באופן זהה ללא תלות במכונת המארח — זה מה שהופך את ההרחבה
האופקית (horizontal scaling) למשמעותית: במקום לבנות שרת אחד גדול יותר,
מריצים יותר עותקים של אותו שרת קטן. זה גם תואם את המגבלות המובנות של
Python: `GameLoop.run_forever` הוא לולאת טיקים (tick loop)
חד-תהליכית (single-threaded), כבולה ל-GIL וסדרתית
(`for game_id, game in self._games.items()`) — תהליך Python לא נעשה
מהיר יותר על ידי הענקת יותר ליבות, אלא רק על ידי הרצת יותר עותקים ממנו.
**שכפלו את התהליך, אל תגדילו אותו.**

**Kubernetes / K3s** מריצים מופעים (instances) רבים של כל תמונה
(image), מטפלים בגילוי שירותים (service discovery) ואיזון עומסים
(load balancing), ומניעים הרחבה אוטומטית (autoscaling) על סמך מדדים
חיים (CPU, זיכרון, מספר חיבורים, מספר חדרים פעילים):

```
100 pods @ 95% CPU → HPA scales up → 150 pods
150 pods @ 10% CPU → HPA scales down → 40 pods
```

K3s הוא אותו מודל בקובץ בינארי (binary) יחיד וקליל — טוב עבור אשכולות
(clusters) בקנה מידה של edge/פיתוח; סביבת production בקנה מידה כזה
זקוקה ל-Kubernetes מלא עם control plane בעל זמינות גבוהה (HA)
(multi-master etcd), כך שהאורקסטרטור (orchestrator) עצמו לא יהווה
נקודת כשל יחידה (single point of failure).

**Docker Compose** עונה על שאלה קטנה יותר ושונה משתי הדוגמאות
הקודמות — לא "האם זה יכול להריץ 10,000 עותקים (replicas)" אלא "האם זה
יכול לרוץ בכלל, על מכונה אחת, לצורך פיתוח מקומי והדגמות": קובץ
`docker-compose.yml` יחיד שמעלה מופע אחד מכל תפקיד (API Gateway, WS
Gateway, Matchmaker, Game Allocator, Game Server Shard אחד, Postgres,
Redis, NATS) מאותן תמונות (images) שה-manifests של K8s/K3s פורסים,
ללא כל מנגנון ה-HPA/multi-node.

**החלוקה המעשית**: תפקידים חסרי מצב (stateless) (Gateways, Auth
Service, Rooms API, Matchmaker, Persistence-writer) הם `Deployment` +
`HorizontalPodAutoscaler` פשוטים. התפקיד שמחזיק מצב סימולציה חי בזיכרון
(Game-Authority / Game Server Shard) הוא בעל מצב (stateful) וזקוק
למנגנון **בעלות (ownership)** מפורש — ראו §4, שם זהו lease מבוסס
Redis המנוהל על ידי Game Allocator. כדאי לציין את **Agones** כחלופה
מוכנה (drop-in) לבנייה מאפס: ה-CRDs שלו —
`Fleet`/`GameServerSet`/`GameServerAllocation` — מספקים בדיוק את
הסמנטיקה הזו של צי (fleet) בעל מצב עם מאגר מוכנות (ready-buffer) באופן
טבעי על Kubernetes, במקום לבנות זאת ידנית ב-Redis.

## 3. סקירת ארכיטקטורה

קבוע (invariant) אחד מתקיים בכל הגרסאות של דיאגרמה זו, בעבר ובהווה,
וכדאי לציין אותו במפורש מכיוון שהוא היה נקודת ביקורת (review) ספציפית:
**לא הלקוח ולא שום Gateway קובעים אי פעם את חוקי המשחק.** ה-`GameEngine`
בתוך ה-shard שבבעלותו נמצא חדר מסוים הוא מקור האמת היחיד
(single source of truth) עבור כל מעבר מצב; ה-Gateways רק מעבירים בתים
(bytes), והלקוח רק מרנדר ומבצע אינטרפולציה (interpolates) למה שה-shard
כבר החליט.

הדיאגרמה שלהלן מאמצת את שמות הרכיבים ואת הצורה מדיאגרמת ביקורת הקורס
(course-review) ישירות — **API Gateway** / **WS Gateway** /
**Matchmaker** / **Game Allocator** / **Game Server Shards** /
**Observability**, **NATS** כאוטובוס האירועים (event bus) הפנימי,
**Agones** כמנהל צי (fleet manager) אופציונלי — הממופים ביחס 1:1 על
התפקידים שמסמך זה כבר טען עבורם. (בסעיפים מוקדמים יותר עדיין נכתב
**Game-Authority**; זה אותו תפקיד בעל מצב (stateful) שהדיאגרמה שלהלן
קוראת לו **Game Server Shard**, הנתמך על ידי אותו קוד `GameLoop` שנדון
ב-§1.) שיפור אחד מהטיוטה המקורית שרד את ההתאמה, ונשמר מסיבה חשבונית
המפורטת ב-§7 ולא הוסר רק כדי להתאים בדיוק לסקיצה — מצוין במקום שבו הוא
מופיע להלן.

```
                              Clients
                    REST/HTTP    │    WebSocket
                        │        │        │
             ┌──────────┘        │        └──────────┐
             ▼                                        ▼
       API Gateway                                WS Gateway
  (stateless — login,                         (stateless — socket
   rooms, history,                              termination, no game
   matchmaking requests)                        logic, publish/
             │                                   subscribe bridge only)
   ┌─────────┴─────────┐                                │
   ▼                   ▼                                │
Auth Service        Rooms API                            │
(stateless)         (stateless)                          │
   └─────────┬─────────┘                                 │
             ▼                                           │
      NATS Event Bus  ◄─────────────────────────────────┘
   (control plane only — low-volume events: matchmaking
    requests, game-created, game-finished, presence)
             │
   ┌─────────┼──────────────────────┐
   ▼                                ▼
Matchmaker                    Game Allocator ◄──── Agones (optional
(shared ELO queue,        (holds the Room                fleet manager:
 Redis sorted set)         Registry lease — §4 —          allocates/health-
             │              picks a Game Server            checks the shard
             └─────────────►Shard for each new room)       fleet)
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
             Game Server       Game Server       Game Server
             Shard (stateful,  Shard             Shard
             owns N rooms,
             authoritative
             GameEngine,
             direct data-plane
             stream to WS Gateway — bypasses NATS, see below)
                    │
                    ▼
             Persistence Workers (stateless consumers of
             "game-finished" events)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   PostgreSQL               Redis
 (users, games,          (presence,
  results, move           matchmaking,
  history)                 leaderboard)
```

*(כל תפקיד שלמעלה מייצא גם אל Observability — לוגים, מדדים, בדיקות
תקינות — הושמט מהתיבות לצורך קריאות; ראו את תת-הסעיף Observability
תחת §9.)*

**שני מעברי תקשורת (transports) שונים, בכוונה תחילה** — המקום היחיד
שבו עיצוב זה מעדן את הסקיצה של הקורס:

- **Control plane** (נפח נמוך: בקשות matchmaking, יצירת חדר,
  game-finished, שינויי נוכחות) — **NATS** (או Redis Pub/Sub, האפשרות
  השנייה שהוזכרה במסמך הקורס), בהתאמה למודל ה-pub/sub שב-§0. נפח נמוך
  מספיק כך שתקורת ה-broker אינה בעיה, וההפרדה (decoupling) בעלת ערך
  (API Gateway שמפרסם בקשת matchmaking לא צריך לדעת איזה shard בסופו
  של דבר יארח אותה).
- **Data plane** (נפח גבוה: זרם המשחק החי, עד 20Hz לחדר פעיל) — stream
  **ישיר** מ-WS Gateway אל ה-Game Server Shard הספציפי שבבעלותו נמצא
  החדר, שנפתר פעם אחת דרך Game Allocator/Room Registry, **לא** מנותב
  דרך NATS בכל טיק. §7 מראה מדוע: בקנה מידה זה, שידור מצב מלא דרך
  קפיצה משותפת (shared hop) מגיע לתעבורה בטווח Tbps, מה שהיה הופך את
  ה-broker עצמו לצוואר הבקבוק. חיפוש (lookup) ב-registry הוא זול;
  ממסר (relay) של כל נפח הנתונים דרך broker אינו זול.

זה גם נותן את תכונת **הבידוד מפני DDoS** שכדאי לשמר מאחת ההצעות
הקודמות: ל-Game Server Shards אין כלל IP ציבורי — כל חבילה חיצונית
מסתיימת ב-Gateway (API או WS) קודם.

## 4. בעלות על חדרים: הפער שקיים בכל עיצוב המבוסס על רישום (registry) בלבד

מיפוי `room_id → worker` (ב-Redis) — המתוחזק על ידי **Game Allocator**
שהוצג ב-§3 — הוא הכרחי אך **לא מספיק**. Pub/Sub מבטיח הפצה (fan-out)
(פרסום אחד מגיע לכל מנוי); הוא לא מבטיח כשלעצמו שרק worker *אחד* אי
פעם מאמין שהוא הבעלים של סמכות הכתיבה על חדר נתון. ללא מנגנון בעלות
מפורש, rebalance או failover לא אמין עלולים לגרום לכך ששני pods של
Game-Authority יקבלו שניהם מהלכים עבור `room_450` — וכעת קיימות שתי
גרסאות סותרות של אותו משחק.

הפתרון: הקצאת חדר היא **lease (חכירה)**, לא רק רשומה ברישום —
`SET room:450:owner worker-B NX PX 5000`, המתחדשת באמצעות heartbeat כל
עוד ה-worker מחזיק בחדר, ומשוחררת (או פשוט פוקעת) בעת כיבוי/קריסה.
worker חדש יכול לקחת בעלות רק לאחר שה-lease אכן פקע, ולעולם לא על ידי
דריסה פשוטה של רשומה חיה. זה מה שהופך את תרחיש הכשל ב-§9 לתקין: הפעלה
מחדש של pod שקרס על ידי Kubernetes היא הכרחית אך לא מספיקה — *פקיעת
ה-lease* היא מה שבפועל מסמיך בעלים חדש.

## 5. שאלה 1 — מסד נתונים עבור 100 מיליון משתמשים רשומים

**SQLite לא מתאים.** לא בעיקר בגלל נפח הנתונים (טבלת משתמשים בת 100
מיליון שורות — אפילו בהערכה נדיבה של כ-1KB לשורה — היא רק כ-100GB,
שנספגים בקלות על ידי RDBMS רגיל). הסיבות האמיתיות:

- **כותב יחיד (single writer)**: SQLite מאפשר טרנזקציית כתיבה אחת בכל
  פעם, גם במצב WAL. עדכוני דירוג (rating) בלבד, מוכפלים בכ-83,000
  משחקים המסתיימים בכל שנייה (§8), יהפכו מיידית לצוואר בקבוק סדרתי
  (serialize into a bottleneck).
- **מוטמע (embedded), לא client-server**: זהו קובץ יחיד על דיסק של
  מכונה אחת. כל תהליך שזקוק לו — Gateway, Auth, Matchmaking,
  Game-Authority, כולם משוכפלים על פני מאות מכונות — יזדקק לגישת מערכת
  קבצים ישירה לאותו קובץ יחיד. אין פרוטוקול רשת לשיתוף שלו בדרך שבה
  Postgres או MySQL מתוכננים לשיתוף.
- **אין שכפול (replication), אין sharding, אין זמינות גבוהה (HA)** —
  קריסה אחת מפילה את כל מערך הנתונים.

**פרסיסטנציה פוליגלוטית (Polyglot persistence), מחולקת לפי דפוס
כתיבה**:

| נתונים | מאגר | מדוע |
|---|---|---|
| חשבונות / אימות (auth) / ELO / משחקים / תוצאות / היסטוריית מהלכים | PostgreSQL/MySQL, primary + read replicas | דורש ACID אמיתי (שם משתמש ייחודי, עדכון דירוג אטומי). 100 מיליון שורות נכנסות בקלות לאשכול (cluster) אחד; מבצעים sharding לפי `user_id` (Citus/Vitess, או CockroachDB/YugabyteDB) ברגע שתפוקת הכתיבה — לא האחסון — הופכת למגבלה. תואם ישירות לדיאגרמה שהוצעה בקורס — מאגר יחסי (relational) יחיד עבור כל נתוני המשחק/המשתמש בני-הקיימא (durable). |
| נוכחות (Presence) / ספריית session | Redis | latency נמוך, לא זקוק ל-durability מעבר ל-TTL; חי באופן טבעי לצד רישום בעלות החדרים (§4). |
| תור Matchmaking | Redis Sorted Set (`ZADD` לפי דירוג) | חיפוש קרבה (proximity lookup) ב-O(log n), משותף גלובלית כך ששחקנים בכל gateway יכולים להיות מותאמים. |
| לוח תוצאות (Leaderboard) | Redis Sorted Set | לא `ORDER BY` חי מעל 100 מיליון שורות — במקום זאת עדכונים אינקרמנטליים. |

*(הערת אגב נחמדה: K3s עצמו משתמש כברירת מחדל ב-SQLite עבור מאגר
הנתונים (datastore) של האשכול שלו, וזקוק ל-etcd/Postgres רק ברגע
שנדרשת זמינות גבוהה (HA) מבוססת multi-node — בדיוק אותו לקח, שכבה אחת
למטה.)*

## 6. שאלה 2 — 10 מיליון שחקנים במקביל: פיזור וניתוב

תהליך אחד לא יכול להחזיק 10 מיליון sockets, וללא קשר לכך, תהליך Python
אחד לא יכול להריץ חישוב טיקים (tick computation) עבור 10M/2 = 5 מיליון
חדרים על ליבה אחת, ללא תלות במספר ה-sockets. שתי העובדות מחייבות פיזור
אופקי (horizontal distribution).

**"כולם יכולים לשחק עם כולם, וכל אחד יכול להצטרף לכל חדר"** עובד
מכיוון שאף לקוח לא צריך לדעת אי פעם *על איזו* מכונה פיזית משהו חי:

1. שחקן מתחבר ל-WS Gateway הקרוב ביותר מבחינה גיאוגרפית (GeoDNS/global
   LB) עבור ה-session החי, ול-API Gateway הקרוב ביותר עבור כל השאר. אף
   אחד מהם לא מחשב שום לוגיקת משחק — WS Gateway רק מחזיק את ה-socket
   ומגשר על תעבורת publish/subscribe; API Gateway מטפל רק בהתחברות
   (login), חדרים, היסטוריה, ובקשות matchmaking (לפי §3).
2. `PLAY` → API Gateway מפרסם בקשת matchmaking אל ה-control plane של
   NATS. Matchmaker רואה **כל** שחקן ממתין באופן גלובלי (תור משותף
   המבוסס על Redis), לא רק שחקנים שפגעו במופע (instance) הספציפי הזה
   של API Gateway. שחקן שהותאם דרך API Gateway בארה"ב ושחקן שהותאם דרך
   API Gateway בטוקיו — שניהם גלויים לאותו תור.
3. לאחר ההתאמה, Matchmaker מעביר את הזוג ל-**Game Allocator**, שרוכש
   lease על בעלות חדר (§4) על Game Server Shard זמין, ומפרסם אירוע
   control-plane בנפח נמוך בשם `game-created` הנושא
   `{room_id, shard_address}` בחזרה דרך NATS אל ה-WS Gateways של שני
   השחקנים.
4. כל WS Gateway פותח stream ישיר בתדירות גבוהה (data-plane) אל אותו
   shard ספציפי — תוך עקיפת NATS, לפי §3. `JOIN_ROOM` עבור `room_id`
   שרירותי עובד באופן זהה: כל WS Gateway שואל את Game Allocator מיהו
   הבעלים הנוכחי ופותח stream מאותו סוג. צופים (spectators) עושים את
   אותו הדבר, רק בלי לקבל אי פעם סמכות כתיבה — מנוי (subscriber) טהור
   של Pub/Sub, ללא צורך ב-lease.

## 7. שאלה 3 — תעבורת רשת: מה בעצם העלות של "מהלך כל 2 שניות"

`_advance_game` שבקובץ `server/game_loop.py` משדר תמונת מצב JSON מלאה
(`full_broadcast_payload` — כל כ-32 הכלים, יומן מהלכים, ניקוד) **בכל
טיק, בתדירות 20Hz, בין אם משהו זז ובין אם לא** — פי 40 יותר לעיתים
קרובות ממה שמרמז "מהלך כל 2 שניות".

| תרחיש | בסיס חישוב | רוחב פס כולל (Aggregate bandwidth) |
|---|---|---|
| הנחת היסוד המילולית: מהלך אחד/2 שניות, הודעה קטנה (כ-100–200 בייט), קפיצה בודדת (single hop) נאיבית | 5M מהלכים/שנייה × כ-150 בייט | כ-6–8 Gbps |
| **הקוד הנוכחי, ללא שינוי**: תמונת מצב מלאה של כ-6KB, בכל טיק 20Hz, שני המושבים | 5M משחקים × 20Hz × 2 מושבים × 6KB | **כ-9.6 Tbps** |
| הקוד הנוכחי + טופולוגיית ממסר (relay) דרך Gateway (קפיצה כפולה) | הערך שלמעלה × 2 | **כ-19 Tbps** |
| **עיצוב היעד**: אירוע דליל (sparse) רק בתחילת תנועה (כלי, ממקור, ליעד, משך זמן), אינטרפולציה בצד הלקוח (client-side) לתנועה חלקה — ללא שידור חוזר תקופתי | כ-5M אירועים/שנייה × כ-150–250 בייט, fan-out פי 2–3 עבור היריב+הצופים, קפיצה כפולה | **כ-20–45 Gbps** |

הפתרון הוא שינוי פרוטוקול, לא רק עוד שרתים: השרת צריך לפרסם רק **את
תחילת התנועה** (מזהה כלי, מקור, יעד, זמן התחלה, משך — שדות ה-
`motion_phase`/cooldown שהמודל כבר עוקב אחריהם), והלקוח מבצע tweening
של האנימציה מקומית עד לאירוע הבא (`arrived`, `captured`). זוהי
אינטרפולציה סטנדרטית בצד הלקוח מתוך אירועים סמכותיים (authoritative)
דלילים, וזהו ההבדל בין השורות של כ-9.6–19 Tbps לבין יעד ה-20–45 Gbps —
האחרון גדול אך שגרתי בקנה מידה של hyperscale, ומתפזר (shards) באופן
טבעי לפי חדר (pod יחיד של Gateway עם כ-20,000 חיבורים נושא רק כ-1–2
MB/s).

## 8. שאלה 4 — משחקים של 30–90 שניות: מה המשמעות עבור תפקידי הקונטיינרים

לפי חוק ליטל (Little's Law): 10 מיליון שחקנים ÷ 2 = 5 מיליון משחקים
במקביל; אורך חיים ממוצע של כ-60 שניות ⇒

```
5,000,000 games ÷ 60s ≈ 83,000 games starting AND finishing every second,
continuously — not a one-time burst.
```

שלוש השלכות, כולן נגזרות ישירות ממספר זה:

1. **לעולם לא קונטיינר אחד למשחק.** תקורת (overhead) תזמון
   pod/cold-start (מאות מילישניות עד כמה שניות) מהווה חלק גדול מאורך
   חיים של 30–90 שניות, ו-83,000 הפעלות pod בשנייה יציפו כל
   אורקסטרטור. יחידת ההרחבה היא תהליך Game-Authority אחד ארוך-טווח
   המארח אלפי משחקים קצרים במקביל (בדיוק מה ש-`GameLoop` כבר עושה) —
   מרחיבים על ידי הוספת יותר תהליכים כאלה, לא יותר קונטיינרים למשחק.
2. **הפרסיסטנציה חייבת להיות אסינכרונית.** כתיבת משחק שהסתיים באופן
   סינכרוני בקצב של 83,000 בשנייה בתוך נתיב הכיבוי (shutdown path) של
   החדר עצמו הייתה גורמת לתקיעה של לולאת הטיקים (tick loop) של
   Game-Authority. במקום זאת, מפרסמים אירוע control-plane בשם
   `game-finished`; Persistence Workers צורכים אותו במנות (batches),
   באופן מנותק (decoupled) משאלת האם ה-DB איטי רגעית.
3. **תפקידים שונים מתחלפים בקצבים שונים**, וזו בדיוק הסיבה שהם חייבים
   להיות תמונות (images) נפרדות של Docker עם מדיניות autoscaling
   נפרדת: חיבורי Gateway שורדים מעבר לכל משחק בודד (שחקן משחק משחקים
   רבים ברצף על אותו socket — ללא תקורת reconnect בין משחקים), קיבולת
   Game-Authority חייבת להגיב תוך שניות מכיוון שהביקוש עצמו מתחלף
   (churns) כל כ-60 שניות, ושכבת ה-DB גדלה באיטיות וביציבות מנפח כתיבה
   מצטבר.

זה גם הופך את **ה-scale-down ואת ה-rolling deploys לזולים**: pod של
Game-Authority שיוצא משימוש מפסיק לקבל חדרים חדשים, מרוקן (drains) את
הקיימים שלו (המתנה חסומה של ≤90 שניות), ואז יוצא — ללא צורך במנגנון
live-migration, בשונה משירות עם sessions הנמשכים שעות.

## 9. מה קורה כאשר שרת נופל — לפי רכיב

| רכיב | בעת כשל | התאוששות |
|---|---|---|
| Gateway | ה-socket של הלקוח מתנתק | חסר מצב (Stateless); N≥3 עותקים (replicas) מאחורי ה-LB; הלקוח מתחבר מחדש לכל Gateway אחר — אין אובדן נתונים, מכיוון ש-Gateway לא מחזיק שום מצב סמכותי (authoritative) |
| Auth / Auth DB | חוסר זמינות קצר של login במהלך failover | primary + standby מנוהלים (למשל Patroni), הבטחה (promotion) אוטומטית |
| Matchmaking | מופע (instance) חלופי ממשיך לסרוק את אותו תור | התור חי ב-Redis, לא בזיכרון של ה-pod של matchmaking — שום דבר לא אבד |
| Redis (registry / queue / leases) | shard הופך לבלתי זמין | Redis Cluster/Sentinel, replica לכל shard, failover אוטומטי; מחולק (sharded) לפי אזור/דירוג כך שהשבתה של shard אחד לא משפיעה על כל העולם |
| ברוקר control-plane (NATS/Kafka) | node של ברוקר נכשל | מקובץ (clustered) עם replication; נפח נמוך יחסית לתעבורת המשחק (§7), כך ששכבה זו קלה יחסית לשמור זמינה |
| **Game-Authority** | **כל חדר שהיה בבעלותו נעלם — מצב בזיכרון (in-memory), לא persisted** | ראו להלן |
| DB של דירוג/פרסיסטנציה | כתיבות מצטברות בתור | Game-Authority לעולם לא נחסם עליו (fire-and-forget אל ברוקר ה-control-plane) — המשחק לא מושפע מ-DB איטי או שנופל לרגע |

### Game-Authority: "רשת ביטחון סבירה", לא מושלמת

checkpoint-and-resume מדויק מבחינה פיזיקלית נשקל ונדחה כלא פרופורציונלי:
כלים יכולים להיות באמצע תנועה (mid-flight), באמצע יירוט
(mid-interception), באמצע cooldown (שוב, ראו את התיאור של README עצמו
לגבי מירוצים (races) ויירוטים) — שחזור מדויק של כך מתוך snapshot
מסתכן ב-replays שגויים באופן גלוי (כלי ש"מבצע קפיצה" (warping) קדימה
בהתאם למשך ההשבתה) עבור תועלת תקינות (correctness) שהיא שולית
בהתחשב בכך שהמשחקים קצרים. במקום זאת:

- **הגבלת רדיוס הפגיעה (blast radius)**: הגבלת מספר החדרים במקביל לכל
  pod של Game-Authority (הנחת תכנון, לא נמדדת עדיין — ראו §10) כך
  שקריסה אחת משפיעה על פלח קטן וידוע מתוך 5 מיליון המשחקים הכולל, ולא
  על כולם.
- **checkpoint הוגנות (fairness) קליל**, לא checkpoint פיזיקלי: שמירת
  (persist) מספיק ל-Redis כל כמה שניות (ניקוד, זמן שחלף, כלים שנותרו)
  — לא מצב אנימציה מדויק באמצע תנועה — כך שבעת קריסה המערכת יכולה
  לקבל החלטה *הוגנת* (ביטול המשחק, ללא קנס דירוג, או הכנסה מחדש
  מיידית של שני השחקנים לתור) במקום resume מלא.
- **בדיקות liveness של Kubernetes** מזהות pod שקרס/נתקע במהירות
  ומפעילות אותו מחדש; ה-**lease** על כל חדר שהחזיק (§4) פוקע מעצמו,
  כך שאף Gateway לא מנתב מצטרף חדש אל worker מת, ו-worker חדש יכול
  לרכוש באופן לגיטימי את מזהה החדר מחדש עבור מה שיבוא הבא.
- לקוחות מושפעים מקבלים שגיאה וחוזרים ל-matchmaking — עלות חסומה
  וידועה מראש, מקובלת בדיוק *מכיוון* שהמשחקים קצרים.

### נראות (Observability): הפיכת מספרי תכנון למדידות

כל תפקיד שלמעלה — שתי שכבות ה-Gateway, Matchmaker, Game Allocator,
Game Server Shards, Persistence Workers — מייצא (exports) את אותם
שלושה דברים למקום מרכזי, במקום להשאיר אותם כידע שבטי (tribal knowledge)
על מכונה אחת:

- **מדדים (Metrics)**: מספר חיבורים וקצב בקשות לכל pod של Gateway,
  עומק תור (queue depth) לכל replica של Matchmaker, מספר חדרים פעילים
  ו-latency של טיקים לכל Game Server Shard, consumer lag לכל
  Persistence Worker. אלה בדיוק האותות (signals) שכללי ה-HPA ב-§2
  וחישוב הקיבולת ב-§10 תלויים בהם — בלעדיהם, "כ-500 חדרים/pod" ו"כ-
  20,000 חיבורים/Gateway" נשארים ניחושים לנצח.
- **לוגים מובנים (Structured logs)**, מתואמים (correlated) לפי
  `room_id`/`user_id`, כך שחקירת תמיכה (support) או אנטי-רמאות
  (anti-cheat) יכולה לעקוב אחר משחק אחד לאורך API Gateway ← Matchmaker
  ← Game Allocator ← Game Server Shard ← Persistence Worker בלי לבצע
  grep ידני על חמש מכונות.
- **בדיקות Health/readiness** — אותן בדיקות liveness של Kubernetes
  שכבר נסמכים עליהן למעלה כדי לזהות Game Server Shard שקרס מספיק מהר
  כדי שה-lease שלו יפקע ותחליף ייקח פיקוד.

**בדיקות עומס (Load testing)** הן מה שהופך את מספרי התכנון שסומנו
לאורך מסמך זה (כ-500 חדרים/pod וכ-20,000 חיבורים/Gateway מ-§10; גודל
הברוקר מ-§12) מהנחות למדידות: לקוחות סינתטיים המניעים טיקים אמיתיים
דרך Game Server Shard אמיתי, נצפים דרך אותו צינור מדדים (metrics
pipeline), לפני שמישהו מהמספרים נסמך עליו בתוכנית קיבולת אמיתית.

## 10. האם הקיבולת באמת מסתכמת נכון?

בהנחה שמרנית של **כ-500 חדרים במקביל לכל Game Server Shard** (payload
יעד של כ-150–250 בייט, תהליך Python אחד ≈ שווה-ערך לחישוב טיקים של
ליבה אחת — הנחת תכנון הממתינה ל-benchmarking אמיתי):

- רוחב פס לכל shard: 500 × 20Hz × כ-200 בייט × 2 מושבים ≈ **כ-8MB/s
  (כ-64Mbps)** — זניח לעומת הקצאה טיפוסית של 1–10Gbps ל-node.
- **shards נדרשים בשיא**: 5,000,000 ÷ 500 = **כ-10,000**, כל אחד מקבל
  חדרים חדשים בקצב של רק כ-8.3/שנייה (83,000 ÷ 10,000) — זול, מכיוון
  שפתיחת חדר היא הקצאה בזיכרון (in-memory) ללא I/O בנתיב החם (hot
  path).
- שכבת Gateway, באופן עצמאי: 10 מיליון חיבורים ÷ כ-20,000/pod ≈
  **כ-500 pods של Gateway**.

עשרת אלפים shards נשמע גדול בבידוד, אך זו התוצאה הישירה והצפויה של קנה
המידה הנדרש — אף רכיב בודד לא צריך להיות עצום, הוא צריך להיות משוכפל
(replicated) הרבה.

## 11. סיכום תפקידים

| תפקיד | מצב (State) | מתקשר עם broker/registry | מתרחב לפי |
|---|---|---|---|
| API Gateway | חסר מצב | מפרסם בקשות matchmaking אל NATS; קורא/כותב מ-Auth Service, Rooms API | קצב בקשות |
| WS Gateway | חסר מצב | גשר (bridge) Pub/Sub (control-plane, דרך NATS) + stream ישיר (data-plane, עוקף את NATS) | חיבורים פתוחים |
| Auth Service | חסר מצב | קורא/כותב מ-DB של Auth/ELO | קצב בקשות |
| Rooms API | חסר מצב | קורא/כותב היסטוריית חדרים | קצב בקשות |
| Matchmaker | מצב משותף ב-Redis | צורך בקשות matchmaking מ-NATS; מעביר זוגות מותאמים ל-Game Allocator | עומק תור |
| Game Allocator | חסר מצב (מבוסס registry) | מחזיק leases של Room Registry (§4, Redis); מפרסם `game-created` אל NATS | קצב הקצאה |
| Agones (אופציונלי) | מנהל צי (Fleet manager) | מקצה/בודק תקינות (health-check) לצי ה-Game Server Shard במקום מנגנון leasing ידני | לא רלוונטי — תשתית עבור צי ה-shards |
| Game Server Shard (בעבר "Game-Authority" — §3) | **בעל מצב (Stateful)** (GameEngine בזיכרון) | stream ישיר data-plane אל WS Gateway; מפרסם `game-finished` אל NATS | מספר חדרים פעילים / CPU |
| NATS Event Bus | אשכול מנוהל (Managed cluster) | תעבורת control-plane בלבד — לעולם לא טיקי משחק (§3) | קצב אירועים (נפח נמוך) |
| Persistence workers | צרכן (consumer) חסר מצב | רשום כמנוי (subscribes) ל-`game-finished` | queue lag |
| DB של Auth/Game (PostgreSQL — חשבונות, ELO, משחקים, היסטוריית מהלכים) | אשכול בעל מצב | — | משתמשים / תפוקת כתיבה |
| Observability | אספנים (Collectors) (חסרי מצב) + TSDB/log store (בעל מצב) | אוסף/מקבל מכל תפקיד שלמעלה | נפח מדדים/לוגים |

## 12. שאלות פתוחות

- **Latency בין אזורים (Cross-region)**: כאשר שני שחקנים מאזורים
  מרוחקים מותאמים, מאגר Game-Authority של איזה אזור מארח את החדר, ומה
  זה עולה מבחינת latency לצד המפסיד? (Matchmaking יכול להטות (bias)
  לכיוון התאמה באותו אזור, עם cross-region רק כ-fallback.)
- **ניתוב Reconnect**: לקוח שהתנתק חייב למצוא את חדרו מחדש דרך *כל*
  Gateway, לא רק זה שהחזיק את ה-socket המקורי — דורש שמיפוי
  הנוכחות/החדר יהיה נגיש גלובלית, מה שהוא כן במבנה כאן, אך צריך להיות
  מאומת תחת תזמון failover אמיתי.
- **קיבולת הברוקר**: יש לגודל (size) במפורש את ברוקר ה-control-plane
  (NATS/Kafka) עבור כ-83,000 אירועי `game-created`/`game-finished`
  בשנייה בתוספת churn של נוכחות — נפח נמוך יחסית לתעבורת המשחק, אך לא
  אפס, וכדאי לבדוק בבדיקת עומס אמיתית ולא כהנחה.
- **משחקים-לכל-pod (כ-500) וחיבורים-לכל-Gateway (כ-20,000)** הם מספרי
  תכנון, לא מדידות — הצעד האמיתי הבא הוא benchmarking של עלות טיק
  בפועל ותקורת socket כדי להחליף אותם בנתונים.
