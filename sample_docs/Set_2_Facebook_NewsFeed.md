# Set 2 — Facebook NewsFeed

---

## Scenario

A feed is a stream of information that appears on a website or app. It can include posts, stories, articles, and other types of content. The feed is usually personalized to show you the most relevant and interesting information based on your past interactions with the site or app. One such example of a feed is the Facebook Newsfeed where content you may be suggested could include:

- Text or image posts from Friends & Family
- Posts from groups you may be in
- People you can add as friends
- Pages/Businesses you might want to follow

We recently launched a new type of content (short videos) in the last couple of months. The Product Manager would like to know how this content is performing and if it is adding value.

---

## Question 1: What business questions would help us understand how the newsfeed is performing after launching short videos?

---

### Clarifying Questions

- Is the short video feature launched globally or only in specific regions?
- Does the short video content appear in the main feed, or does it have a dedicated section?

---

### Engagement
- Are users interacting with the short videos?
- Has the overall engagement rate been impacted since the launch?

### Viewership
- How does viewership of short videos compare to other content types?
- Are users spending more time on the platform after the launch?

### Retention
- Has retention improved since introducing short videos?
- How has churn been affected by the new feature?

### Revenue
- Has ad revenue shown any noticeable change post-launch?
- Has the average revenue per user improved?

### User Satisfaction
- Are users satisfied with the new content?
- Have we seen a rise or decline in new user sign-ups?

---

## Question 2: What metrics would you define to help answer the business questions?

---

- **DAU (Daily Active Users)** — *(count of distinct users per day)*
- **MAU (Monthly Active Users)** — *(count of distinct users per month)*
- **Engagement Rate** — *((engaged users / total users) * 100)*
- **Total Views** — *(sum of all view events)*
- **Unique Users** — *(count of distinct user IDs)*
- **Avg Time Spent** — *(total view time / total sessions)*
- **Valid View Rate** — *(views ≥ 3 seconds / total views) * 100*
- **Actioned View Rate** — *(views with reaction/like/comment/share / total views) * 100*
- **Retention Rate** — *((users at end of period / users at start) * 100)*
- **Churn Rate** — *((users lost / users at start) * 100)*
- **NPS Score** — *(%promoters - %detractors)*
- **CSAT Score** — *((satisfied customers / total respondents) * 100)*
- **Sentiment Score** — *((positive mentions - negative mentions) / total mentions)*
- **Ad Revenue** — *(sum of ad revenue)*
- **ARPU (Avg Revenue Per User)** — *(total revenue / total users)*

---

## Question 3: What are the most important dimensions / cuts relevant to your metrics?

---

### Content
- Type (video, photo, text)
- Duration
- Quality
- Language
- Origin Country
- Created Date
- Genre / Category
- Privacy

### User
- Age
- Gender
- Signup Date
- Preferred Language
- Origin Country
- Type (new vs returning)

### User Behaviour
- New vs Returning
- Frequency of Use
- Viewing Patterns (likes, shares, comments)

### Time
- Day of Week
- Weekend vs Weekday
- Seasonality / Holiday

### Device
- Make
- Model
- App Version
- OS / Browser Type

### Location
- Country
- Region
- City
- Zip Code

---

## Question 4: How would you visualize your metrics and dimensions in a dashboard?

---

- **DAU/MAU trend over time, broken down by content type** → Multi-Line Chart
  - X-axis: Time | Y-axis: Active Users | Lines segmented by content type

- **Total Views over time, broken down by genre** → Stacked Bar Chart
  - X-axis: Time | Y-axis: Total Views | Bars segmented by genre

- **Avg Time Spent by content category** → Bar Chart
  - X-axis: Category | Y-axis: Avg Time Spent

- **Revenue by content type** → Pie Chart
  - Segments: short video, photo, text, other

- **Acquisition Funnel** → Funnel Chart
  - Visitors → Sign Ups → Active Users → Retained Users

---

## Question 5: What automatic checks or monitoring would you add to detect potential issues?

---

- **Data Quality Checks** — Validates completeness, accuracy, and validity of data fields
- **Freshness Checks** — Monitors whether data is being updated within expected timeframes; alerts when data becomes stale
- **Data Consistency** — Ensures data is uniform across different systems, tables, or time periods
- **Data Integrity Checks** — Verifies referential integrity and constraint validation throughout the data lifecycle
- **Anomaly Detection** — Identifies unusual patterns or outliers that deviate from expected behaviour
- **Statistical Analysis** — Uses standard deviation to detect anomalies. Values beyond 2–3 SDs from the mean are flagged. Example: if avg daily views = 1,000,000 with SD = 100,000, values below 700,000 or above 1,300,000 trigger alerts. Z-score: `z = (value - mean) / SD`
- **User Feedback Checks (NPS, CSAT)** — Monitors satisfaction metrics and feedback to detect product issues early

---

## Question 6: Design a data model to support the tracked metrics and dimensions.

**Tracked Metrics:**
- Valid-views / Views — valid views = views with at least 3 seconds of watch time
- Actioned-views / Views — actioned views = views with reactions/likes/comments/shares

**Tracked Dimensions:** content dimensions, user demographics

---

### Business Process

user opens feed → content impression → view → react / like / comment / share / report (or scroll past)

---

### Key Entities

- User
- Content
- Device
- Location
- Event

---

### `dim_user`

| Column | Notes |
|---|---|
| user_id (PK) | |
| type | |
| age | |
| gender | |
| signup_date | |
| language | |
| origin_country | |
| location_id (FK) | |
| date | Snapshot partitioned |

---

### `dim_content`

| Column | Notes |
|---|---|
| content_id (PK) | |
| creator_id (FK) | |
| original_creator_id | For shared content — points to the original creator |
| type | video, photo, text |
| duration | |
| creation_date | |
| language | |
| origin_country | |
| privacy | |
| date | Snapshot partitioned |

---

### `dim_device`

| Column | Notes |
|---|---|
| device_id (PK) | |
| make | |
| model | |
| version | |
| date | Snapshot partitioned |

---

### `dim_location`

| Column | Notes |
|---|---|
| location_id (PK) | |
| country | |
| region | |
| city | |
| zip_code | |
| date | Snapshot partitioned |

---

### `fct_events`

Grain: 1 row per event per user per content

| Column | Notes |
|---|---|
| event_id (PK) | |
| user_id (FK) | |
| content_id (FK) | |
| device_id (FK) | |
| location_id (FK) | |
| session_id | |
| event_type | view, like, react, comment, share, report, repost |
| event_value | rating value, reaction type, etc. |
| event_start_ts | |
| event_end_ts | |
| is_shared | True / False — flags shared content events |
| date | Incrementally partitioned |

---

### Relationships

- `dim` → `fact`: 1:M — one user/content/device can appear in many events
- `fact` → `dim`: 1:1 — each event row points to exactly one dim record per FK

---

## Follow-up: Shared Content Extension

Some content in the newsfeed is shared content — user 1 shares a post created by user 2, and it appears on user 3's feed. It can be re-shared multiple times. To answer questions like "total reactions across all shared content for a given day":

- `is_shared` flag is added to `fct_events` (already included above)
- `original_creator_id` is added to `dim_content` to trace back to the original creator regardless of how many times it's been re-shared

This lets you query:

```sql
-- Total reactions on shared content today
SELECT COUNT(*) AS total_reactions_on_shared
FROM fct_events
WHERE date = CURRENT_DATE
  AND event_type = 'react'
  AND is_shared = TRUE;
```

---

## SQL Questions

### Table Schemas

#### `fct_newsfeed_action`

| Column | Data Type |
|---|---|
| date | date (partition) |
| user_id | bigint |
| session_id | varchar |
| content_id | bigint |
| action_id | bigint |
| action_type | varchar (view / report / comment / react / share) |
| view_start | datetime |
| view_end | datetime |

#### `dim_content`

| Column | Data Type |
|---|---|
| date | date (partition) |
| content_id | bigint |
| content_type | varchar (photo / video / text) |
| creator_id | bigint |
| creation_date | date |
| video_length_seconds | integer (NULL for non-video content) |
| last_update_date | date |

---

### Q1: For video content today — % watched to full duration, total watch time, avg watch time

```sql
WITH videos_today AS (
    SELECT
        content_id,
        video_length_seconds
    FROM dim_content
    WHERE date = CURRENT_DATE
      AND content_type = 'video'
),
views_today AS (
    SELECT
        content_id,
        EXTRACT(EPOCH FROM (view_end - view_start)) AS watched_seconds
    FROM fct_newsfeed_action
    WHERE date = CURRENT_DATE
      AND action_type = 'view'
      AND view_end IS NOT NULL
)
SELECT
    ROUND(100.0 * SUM(CASE WHEN vw.watched_seconds >= v.video_length_seconds THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 2) AS pct_full_duration,
    SUM(vw.watched_seconds) AS total_watch_time_seconds,
    ROUND(AVG(vw.watched_seconds), 2) AS avg_watch_time_seconds
FROM videos_today v
JOIN views_today vw ON v.content_id = vw.content_id;
```

---

### Q2: % of content created today that had at least 1 reaction and 0 comments today

```sql
WITH content_today AS (
    SELECT content_id
    FROM dim_content
    WHERE date = CURRENT_DATE
      AND creation_date = CURRENT_DATE
),
content_actions AS (
    SELECT
        content_id,
        SUM(CASE WHEN action_type = 'react' THEN 1 ELSE 0 END) AS total_reactions,
        SUM(CASE WHEN action_type = 'comment' THEN 1 ELSE 0 END) AS total_comments
    FROM fct_newsfeed_action
    WHERE date = CURRENT_DATE
      AND action_type IN ('react', 'comment')
    GROUP BY content_id
)
SELECT
    ROUND(100.0 * SUM(CASE WHEN ca.total_reactions >= 1 AND ca.total_comments = 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(ct.content_id), 0), 2) AS pct_reaction_no_comment
FROM content_today ct
LEFT JOIN content_actions ca ON ct.content_id = ca.content_id;
```

---

## Python Questions

### Q1: Fixed-size buffer metrics from a real-time event stream

**Problem:** Process a stream of user events through a fixed-size buffer. Every time the buffer fills to capacity, compute and print engagement metrics — ignoring any test content events. Then slide the window by removing the oldest event.

**Input:**

```python
stream = [
    {'post_id': 101, 'viewed_time_ms': 6500, 'engaged_with_post': 1},
    {'post_id': 104, 'viewed_time_ms': 200,  'engaged_with_post': 1},
    {'post_id': 105, 'viewed_time_ms': 4200, 'engaged_with_post': 0, 'is_test_content': True},
    {'post_id': 108, 'viewed_time_ms': 4499, 'engaged_with_post': 1},
    {'post_id': 105, 'viewed_time_ms': 500,  'engaged_with_post': 1},
]
```

**Expected Output:**
```
You've got 2 engagements and spent 6.7s viewing content. Post ids: 101, 104
You've got 2 engagements and spent 4.699s viewing content. Post ids: 104, 108
You've got 2 engagements and spent 4.999s viewing content. Post ids: 108, 105
```

**Solution:**

```python
def process_stream(stream, capacity):
    buf = []

    for event in stream:
        buf.append(event)

        if len(buf) == capacity:
            num_eng = 0
            time_ms = 0
            post_ids = []

            for item in buf:
                if not item.get('is_test_content', False):
                    num_eng += item['engaged_with_post']
                    time_ms += item['viewed_time_ms']
                    post_ids.append(str(item['post_id']))

            time_s = time_ms / 1000
            print(
                f"You've got {num_eng} engagement{'s' if num_eng != 1 else ''} "
                f"and spent {time_s}s viewing content. "
                f"Post ids: {', '.join(post_ids)}"
            )
            buf.pop(0)

process_stream(stream, 3)
```
