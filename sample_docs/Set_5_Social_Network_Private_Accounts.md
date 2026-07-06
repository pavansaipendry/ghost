# Set 5 — Social Network Private Accounts

---

## Scenario

We recently introduced private accounts to a popular social networking platform where users can share photos, videos, and updates. For public accounts, anyone can follow and view content. For private accounts, a user must approve a follow request before the requester can view their content. Since the launch of private accounts, we have noticed overall engagement on the platform has declined. You are now part of a team formed to investigate the change.

---

## Question 1: What are your next steps? How would you approach this problem?

---

### Clarifying Questions

- How long has it been since launch, and is engagement still declining or has it stabilised?
- Did many high-influence accounts go private?
- What specific metrics declined — is it likes, comments, DAU, MAU?

---

### Investigation Areas

*(write: Data Quality | Bugs | Content Discovery | Follower Growth | Composition Shift | Behavioural Changes)*

#### Data Quality Issues *(write: pipeline failures, data freshness, logic errors)*
Before drawing any conclusions, I'd first validate whether the drop is real or a data issue — pipeline failures, NULL values, or incorrect joins can all create a false signal. If it's a data issue, fixing it is the first step.

#### Bugs in the Logic *(write: unintended content restriction)*
I'd review whether there are bugs in the private account implementation that unintentionally restrict content visibility more than intended — for example, private posts accidentally being removed from feeds of already-approved followers.

#### Content Discovery Problem *(write: low impressions, removed from feed)*
Private content is likely removed from public feeds. This directly reduces impressions per post, which reduces the surface area for engagement even for content people would have engaged with.

#### Slower Follower Growth *(write: manual approval, reduced reach loop)*
Private accounts require manual approval of follow requests. This creates friction in follower growth — fewer new followers means reduced reach, which feeds back into lower engagement.

#### User Composition Shift *(write: high-follower accounts going private)*
If high-follower accounts — influencers, public figures — went private, the platform loses a disproportionate share of its total engagement surface. I'd check what percentage of top-engaging accounts switched.

#### Behavioral Changes *(write: posting less, loss of public validation)*
Private users may post less frequently because the incentive of public visibility is removed. Loss of public validation (likes, reach) reduces posting motivation, which reduces overall content volume.

---

## Question 2: What metrics would you look at to understand the engagement decline?

---

- **Number of Engagements** — total count of likes, comments, shares, saves, reposts *(sum of all engagement events)*
- **Avg Engagements per Post** — *(total engagements / total posts)*
- **Engagement Rate** — *(engagements / impressions or reach) * 100*
- **Retention Rate** — *(users active at end of period / users at start) * 100*
- **Churn Rate** — *(users lost / total users at start) * 100*
- **Avg Follower Growth Rate** — *(new followers gained / total followers) * 100 per period*
- **Follower Acceptance Rate** — *(accepted follow requests / total follow requests) * 100*
- **Avg Time to Accept Follow Request** — *(avg(acceptance_ts - request_ts))*
- **% Accounts Switching Public → Private** — *(daily count of switches / total accounts) * 100*
- **% Private vs Public Accounts** — *(private accounts / total accounts) * 100*

---

## Question 3: What are the most important dimensions / cuts for your metrics?

---

### User Demographics
- Age
- Gender
- Origin Country
- Language
- Signup Date

### Types of Engagements
- Likes
- Shares
- Comments
- Saves
- Reposts

### Types of Posts
- Reels
- Stories
- Photos
- Videos

### Account Types
- Public
- Private

### Content Creator Cohort
- Influencers
- Regular Users

### Time Periods
- Time of Day
- Day of Week
- Weekday vs Weekend
- Holidays / Seasons

---

## Question 4: Design a data model to support the investigation.

**Track:**
- Follow Requests: number of requests initiated by public/private accounts
- Acceptance Rate: rate of accepted follow requests
- Following Relationships: which users each account follows
- Engagement: patterns and decline in user interaction

---

### Business Process

user signup (public or private) → create content → set visibility → send/receive follow requests → accept/reject → engage with content (like, comment, share, save)

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
| username | |
| age | |
| gender | |
| email | |
| language | |
| origin_country | |
| signup_date | |
| account_type | public / private |
| followers_count | |
| following_count | |
| location_id (FK) | |
| last_active | |
| date | Snapshot partitioned |

---

### `dim_content`

| Column | Notes |
|---|---|
| content_id (PK) | |
| content_type | reel, story, photo, video |
| category | |
| user_id (FK) | |
| duration | |
| song_attached | |
| created_at | |
| date | Snapshot partitioned |

---

### `dim_device`

| Column | Notes |
|---|---|
| device_id (PK) | |
| make | |
| model | |
| os | |
| version | |
| browser_type | |
| date | Snapshot partitioned |

---

### `dim_location`

| Column | Notes |
|---|---|
| location_id (PK) | |
| zip | |
| city | |
| region | |
| country | |
| date | Snapshot partitioned |

---

### `fct_event_interactions`

Grain: 1 row per engagement event per user per content

| Column | Notes |
|---|---|
| event_id (PK) | |
| user_id (FK) | |
| content_id (FK) | |
| device_id (FK) | |
| location_id (FK) | |
| session_id | |
| action_type | like, share, save, repost, comment, view |
| action_value | |
| start_ts | |
| end_ts | |
| date | Incrementally partitioned |

---

### `fct_user_followers` (M:M bridge)

Tracks all follow-related events between users.

| Column | Notes |
|---|---|
| follow_id (PK) | |
| source_user_id (FK) | the user sending the request |
| target_user_id (FK) | the user receiving the request |
| event | follow_request, follow_accept, follow_success, reject, unfollow |
| event_details | |
| event_ts | |
| date | Incrementally partitioned |

---

### Relationships

- `dim` → `fact`: 1:M — one user/content/device appears across many events
- `fact` → `dim`: 1:1 — each event row points to exactly one dim record per FK
- `fct_user_followers`: M:M — one user can follow many users and be followed by many users

---

## Data Model Extension Questions

### Q1: How do you get follower count?
Add `followers_count` and `following_count` directly to `dim_user` (updated via snapshot). For real-time counts, query `fct_user_followers` grouping by `target_user_id` where `event = 'follow_accept'`.

### Q2: How do you track who is following whom?
Use the `fct_user_followers` bridge table — each active follow relationship has a row with `event IN ('follow_accept', 'follow_success')`. For a snapshot of active connections, build `int_accept_user` as an intermediate table.

#### `int_accept_user`

| Column | Notes |
|---|---|
| user_id | |
| follower_id | |
| is_reciprocal | True / False |
| event | follow_accept |
| date | Partition |

### Q3: How do you identify reciprocal follows?
Add `is_reciprocal` to `int_accept_user`. A follow is reciprocal if both (A→B) and (B→A) rows exist in the table with `event = 'follow_accept'`.

### Q4: How do you track all engagements across users?
Use `fct_event_interactions` for individual events. For aggregated reporting, use `agg_user_engagement_summary`.

#### `agg_user_engagement_summary`

| Column | Notes |
|---|---|
| user_id | |
| total_likes | |
| total_comments | |
| total_shares | |
| total_saves | |
| total_reposts | |
| total_engagements | |
| date | Partition |

---

## SQL Questions

### Table Schemas

#### `dim_user`

| Column | Data Type |
|---|---|
| user_id | bigint |
| privacy_setting | varchar (private / public) |
| privacy_setting_last_update_ts | timestamp |
| date | date (partition) |

#### `fct_follows`

| Column | Data Type |
|---|---|
| source_user | bigint (request sender) |
| target_user | bigint (request acceptor / rejector) |
| event_action | varchar (follow_request / follow_accept / follow_success / reject / unfollow) |
| action_ts | timestamp |
| date | date (partition) |

#### `dim_follows` (derived — used in Q2)

| Column | Data Type |
|---|---|
| source_user_id | bigint |
| target_user_id | bigint |
| follow_time | timestamp |
| date | date (partition) |

---

### Q1: Active connections between users at end of day

An active connection exists when User A follows User B and the last event between that pair is a valid follow (`follow_accept` or `follow_success`) — not an unfollow.

```sql
WITH last_event_per_pair AS (
    SELECT
        source_user,
        target_user,
        MAX(action_ts) AS last_action_ts
    FROM fct_follows
    WHERE event_action IN ('follow_accept', 'follow_success', 'unfollow')
    GROUP BY source_user, target_user
)
SELECT
    DATE(f.action_ts) AS date,
    f.source_user,
    f.target_user,
    f.action_ts AS follow_time
FROM fct_follows f
INNER JOIN last_event_per_pair l
    ON  f.source_user = l.source_user
    AND f.target_user = l.target_user
    AND f.action_ts   = l.last_action_ts
WHERE f.event_action IN ('follow_accept', 'follow_success');
```

> The CTE first finds the most recent event per pair. The outer query then filters for pairs where that latest event was a valid follow — correctly excluding pairs where the last event was an unfollow.

---

### Q2: Add `is_reciprocal` column to `dim_follows`

A reciprocal relationship exists if User A follows User B AND User B also follows User A.

**Input:**

| date | source_user_id | target_user_id | follow_time |
|---|---|---|---|
| 2024-09-30 | 101 | 202 | 2024-09-30 11:30:00 |
| 2024-09-30 | 202 | 101 | 2024-09-30 13:00:00 |
| 2024-09-30 | 103 | 204 | 2024-09-30 14:00:00 |
| 2024-09-30 | 107 | 210 | 2024-09-30 14:45:00 |

**Expected Output:**

| date | source_user_id | target_user_id | follow_time | is_reciprocal |
|---|---|---|---|---|
| 2024-09-30 | 101 | 202 | 2024-09-30 11:30:00 | true |
| 2024-09-30 | 202 | 101 | 2024-09-30 13:00:00 | true |
| 2024-09-30 | 103 | 204 | 2024-09-30 14:00:00 | false |
| 2024-09-30 | 107 | 210 | 2024-09-30 14:45:00 | false |

```sql
SELECT
    f.date,
    f.source_user_id,
    f.target_user_id,
    f.follow_time,
    CASE
        WHEN r.source_user_id IS NOT NULL THEN TRUE
        ELSE FALSE
    END AS is_reciprocal
FROM dim_follows f
LEFT JOIN dim_follows r
    ON  f.source_user_id = r.target_user_id
    AND f.target_user_id = r.source_user_id
    AND f.date           = r.date;
```

> Self-join `dim_follows` on swapped source/target. If a matching reverse row exists the LEFT JOIN is non-NULL → reciprocal = TRUE, otherwise FALSE.

---

### Q3: For users who went private in the last 7 days — count of requesters, avg/min/max acceptance rate

```sql
WITH private_mode_users AS (
    SELECT user_id
    FROM dim_user
    WHERE privacy_setting = 'private'
      AND privacy_setting_last_update_ts >= CURRENT_DATE - INTERVAL '6 days'
      AND privacy_setting_last_update_ts <= CURRENT_DATE
      AND date = CURRENT_DATE
),
per_target_stats AS (
    SELECT
        f.target_user,
        SUM(CASE WHEN f.event_action IN ('follow_accept', 'follow_success') THEN 1 ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN f.event_action = 'follow_request' THEN 1 ELSE 0 END), 0) AS acceptance_rate
    FROM fct_follows f
    INNER JOIN private_mode_users p ON f.target_user = p.user_id
    WHERE f.action_ts >= CURRENT_DATE - INTERVAL '6 days'
      AND f.action_ts <= CURRENT_DATE
    GROUP BY f.target_user
)
SELECT
    COUNT(target_user)              AS count_of_requesters,
    ROUND(AVG(acceptance_rate), 2)  AS avg_acceptance_rate,
    ROUND(MIN(acceptance_rate), 2)  AS min_acceptance_rate,
    ROUND(MAX(acceptance_rate), 2)  AS max_acceptance_rate
FROM per_target_stats;
```

---

## Python Questions

### Q1: Reciprocal Follow Count

Given a dictionary where each key is a user and the value is a list of users they follow, return the number of reciprocal follows for each user.

**Input:**

```python
user_follows = {
    'A': ['B', 'C', 'D'],
    'B': ['A', 'D', 'E'],
    'C': ['A', 'D', 'E'],
    'D': ['A', 'E', 'F'],
    'E': ['B', 'C', 'F'],
    'F': ['C', 'D', 'E']
}
```

**Expected Output:**

```python
{'A': 2, 'B': 2, 'C': 2, 'D': 2, 'E': 3, 'F': 2}
```

**Approach:**
1. Loop through each user
2. For each person they follow, check: does that person also follow them back?
3. Count how many do — that's the reciprocal count

**Solution:**

```python
def reciprocal_follow_count(user_follows):
    result = {}
    for user, following_list in user_follows.items():
        count = 0
        for person in following_list:
            if person in user_follows and user in user_follows[person]:
                count += 1
        result[user] = count
    return result

print(reciprocal_follow_count(user_follows))
```

---

### Q2: Friend of a Friend Recommendations

Return friend recommendations for each user. A user should be recommended if they are a friend of a friend — but not already a direct friend or the user themselves.

**Input:**

```python
user_follows = {
    'A': ['B', 'C', 'D'],
    'B': ['A', 'C', 'D'],
    'C': ['A', 'B', 'E'],
    'D': ['A', 'E', 'F'],
    'E': ['B', 'C', 'F'],
    'F': ['C', 'D', 'E']
}
```

**Expected Output:**

```python
{
    'A': ['E', 'F'],
    'B': ['E', 'F'],
    'C': ['D', 'F'],
    'D': ['B', 'C'],
    'E': ['A', 'D'],
    'F': ['A', 'B']
}
```

**Approach:**
1. Loop through each user
2. Get their direct friends list
3. For each direct friend, look at their friends (friends of friends)
4. If the FoF is not the user themselves and not already a direct friend — add to recommendations
5. Return sorted list

**Solution:**

```python
def friend_recommendations(user_follows):
    result = {}
    for user, direct_friends in user_follows.items():
        recommended = set()
        for friend in direct_friends:
            for fof in user_follows.get(friend, []):
                if fof != user and fof not in direct_friends:
                    recommended.add(fof)
        result[user] = sorted(recommended)
    return result

print(friend_recommendations(user_follows))
```

---

### Q3: Combined — Reciprocal Count and Friend Recommendations

Return both the reciprocal count and friend recommendations for each user as a tuple.

**Input:**

```python
user_follows = {
    'A': ['B', 'C', 'D'],
    'B': ['A', 'C', 'D'],
    'C': ['A', 'B', 'E'],
    'D': [],
    'E': ['F'],
    'F': ['E']
}
```

**Expected Output:**

```python
'A': (2, ['E']),       # reciprocal: B, C     | recs: E
'B': (2, ['E']),       # reciprocal: A, C     | recs: E
'C': (2, ['D', 'F']), # reciprocal: A, B     | recs: D, F
'D': (0, []),          # reciprocal: none     | recs: none
'E': (1, []),          # reciprocal: F        | recs: none
'F': (1, [])           # reciprocal: E        | recs: none
```

**Solution:**

```python
def combined(user_follows):
    result = {}
    for user, direct_friends in user_follows.items():

        # Reciprocal count
        count = 0
        for person in direct_friends:
            if user in user_follows.get(person, []):
                count += 1

        # Friend recommendations
        recommended = set()
        for friend in direct_friends:
            for fof in user_follows.get(friend, []):
                if fof != user and fof not in direct_friends:
                    recommended.add(fof)

        result[user] = (count, sorted(recommended))

    return result

output = combined(user_follows)
for user, value in output.items():
    print(f"{user}: {value}")
```
