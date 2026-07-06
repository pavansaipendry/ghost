# Set 4 — DoorDash / Grocery Delivery

---

## Scenario

### Food Delivery App (DoorDash-style)

We recently launched a food ordering app (similar to DoorDash, Grubhub). This app allows customers to order items for takeout or delivery. Within the app, there is an interface for customers to browse menus, select their restaurant, place orders, and select the delivery method (e.g. pickup or delivery).

---

## Question 1: As part of the Analytics team, we need to evaluate how different restaurants/stores are performing on the app. What metrics and dimensions should we consider?

---

### Clarifying Questions

- Did the app launch in a specific region or is it a country-wide launch?
- Do we have any premium plans or is it a free plan for everyone?

---

### Metrics

#### Revenue Metrics

- **Gross Merchandise Value (GMV) per Store** — Total dollar value of all orders before any deductions
- **Average Order Value** — Total Revenue / Total Orders
- **Revenue per Store** — Actual revenue a store receives after discounts from promotional codes or fees
- **Revenue Growth Rate** — Percentage change in revenue over a time period: (Current Period Revenue - Previous Period Revenue) * 100 / Previous Period Revenue

#### Order Metrics

- **Total Number of Orders**
- **Order Completion Rate** — (Completed Orders / Total Orders Placed) * 100
- **Cancelled Order Rate** — (Cancelled Orders / Total Orders) * 100
- **Order Frequency** — Orders per day / orders per hour. Higher velocity means more consistent demand.
- **Refund Rate** — Percentage of orders refunded
- **Avg Prep Time**

#### Customer Metrics

- **Number of Unique Customers per Store**
- **New Customer Acquisition Rate**
- **Repeat Customer Rate** — (Customers with 2+ Orders / Total Unique Customers) * 100
- **Customer Retention Rate** — Proportion of returning customers among existing ones
- **Customer Churn Rate** — Rate at which customers stop ordering from the platform

#### Quality Metrics

- **CSAT** — Average score on overall satisfaction level (scale 1-5)
- **NPS** — Measures loyalty of customers recommending to a friend or the store. Promoters - Detractors.
- **App Ratings** — Ratings for specific stores

---

### Dimensions / Cuts

#### User
- Age
- Gender
- Location
- Signup Date
- Email
- New vs Returning Customers
- Free vs Premium Subscribers

#### Order
- Type (pickup / delivery)
- Size (small, medium, large)
- Value
- First Time vs Repeat Orders

#### Store
- Type (grocery / pharmacy / restaurant)
- Size (small / medium / large)
- Store Chain / Brand
- Premium vs Standard Stores

#### Time
- Time of Day
- Day of Week
- Seasonality / Holidays

#### Location
- Region
- Country
- State
- City
- Zip Code
- Urban vs Suburban vs Rural
- Population Density Zone

#### Product
- Category
- Price range
- In-stock vs out-of-stock

---

## Question 2: The app has been launched for a few months. Our metrics are showing that average revenue per restaurant is trending down, week over week. How would you triage the root cause of this decline?

---

### Clarifying Questions

- Is the decline universal or localized?
- When did the decline start?

---

### Confirm the Metric

Average Revenue per Store = Total Revenue / Total Stores

Possible causes:
- Decreasing number of orders or order value
- Increase in the number of stores
- Both — revenue has decreased and number of stores might have increased at the same time

---

### Debugging the Decline

#### Analyze Pipelines and Upstream Sources
- Data quality issues like NULL or missing data
- Logic issues — incorrect joins, filters

#### Decompose Revenue into Components
- Revenue = Number of Orders × Average Order Value
- Is the order volume decreasing?
- Is average order value decreasing?

#### Check if New Stores Have Been Added
- Total new stores over time

#### Breakdown Revenue by Different Cuts
- By region, store type, order type to see if there is any correlation with the drop
- Average revenue per each breakdown category

#### Internal Factors
- New feature launch — check metrics before and after launch
- New version launch — breakdown by version type
- Bugs from code releases — crash rate
- UI changes
- Marketing changes

#### External Factors
- Competition — discounts by competitors, new restaurants launched
- Global issues
- Seasonality or holidays

#### Check Whether Users Are Entering the App
- Metrics to check — DAU (Daily Active Users)
- Add funnel analysis

---

## Question 3: To encourage customer loyalty and drive more users to the app, what product features would you suggest the team implement?

---

### Retain Existing Customers
- Loyalty and reward programs like cashbacks
- Improve experience with quality assurance and responsive support
- Improve UI
- Easier ordering flow
- Improve order tracking
- Referral discounts
- Faster delivery

### Attract New Customers
- Referral programs
- First order promotions
- Paid advertising
- Reward points
- Coupons
- Offers

---

## Question 4: Design a data model for product analytics.

Some examples of questions we should be able to answer using the data model:
1. How many orders were placed and from which stores?
2. What is the average order size and value?

---

### `dim_customer`

| Column | Notes |
|---|---|
| customer_id (PK) | |
| name | |
| email | |
| phone_number | |
| signup_date | |
| age | |
| gender | |
| is_driver | Boolean flag |
| date | Snapshot partitioned |

---

### `dim_store`

| Column | Notes |
|---|---|
| store_id (PK) | |
| name | |
| category | |
| type | |
| chain | |
| size | |
| location | |
| delivery_available | |
| phone_number | |
| owner_name | |
| date | Snapshot partitioned |

---

### `dim_product`

| Column | Notes |
|---|---|
| product_id (PK) | |
| store_id (FK) | |
| name | |
| category | |
| size | |
| ingredients | |
| mrp_price | |
| retail_price | |
| date | Snapshot partitioned |

---

### `dim_location`

| Column | Notes |
|---|---|
| location_id (PK) | |
| country | |
| region | |
| city | |
| state | |
| zipcode | |
| date | Snapshot partitioned |

---

### `fct_orders`

| Column | Notes |
|---|---|
| order_id (PK) | |
| store_id (FK) | |
| product_id (FK) | List of products |
| customer_id (FK) | |
| driver_id | |
| order_type | pickup, delivery |
| order_accepted_ts | |
| order_ready_ts | |
| driver_assigned_ts | |
| driver_reached_ts | |
| driver_delivered_ts | |
| order_status | |
| cancellation_ts | |
| cancellation_reason | |
| total_items | |
| total_order_cost | |
| app_fee | |
| driver_fee | |
| store_net_amount | |
| date | Incrementally partitioned |

---

### `dim_order_products` (Bridge Table)

| Column | Notes |
|---|---|
| order_product_id (PK) | |
| order_id (FK) | |
| product_id (FK) | |
| name | |
| price | |
| quantity | |
| date | |

---

### Derived Metrics

- **Avg Order Size** = Total Number of Items Ordered / Total Number of Orders
- **Avg Order Value** = Total Cost of All Orders / Total Number of Orders

---

## Question 5 (Extension): A single store can have multiple menus with different items (e.g. lunch, dinner) / multiple product categories. How would you modify the data model to account for this?

---

### Relationships

- A single store can have multiple menus (categories)
- Each menu can have different items (products)
- A single product can belong to multiple categories — for example, bread as (bakery, snack), yogurt as (dairy, organic produce), chicken as (meat, frozen foods)

#### Product ↔ Category Cardinality

- 1 product → multiple categories (1:M)
- 1 category → multiple products (1:M)
- Overall relationship is **M:M** — resolved using a bridge table (`dim_product_category`)

---

### `dim_category`

| Column | Notes |
|---|---|
| category_id (PK) | |
| store_id (FK) | |
| name | |
| time_served | e.g. lunch, dinner (for restaurant menus) |
| date | Snapshot partitioned |

---

### `dim_product_category` (Bridge Table — many-to-many between products and categories)

| Column | Notes |
|---|---|
| category_product_id (PK) | |
| product_id (FK) | |
| category_id (FK) | |
| category_type | |
| store_id (FK) | |
| name | |
| size | |
| price | |
| ingredients | |
| date | Snapshot partitioned |

---

## SQL Questions

### Table Schemas

#### `dim_users`

| Column | Data Type |
|---|---|
| user_id | bigint |
| name | varchar |
| phone | varchar |
| email | varchar |
| registration_date | date |
| city | varchar |
| account_plan | varchar (e.g. 'free', 'premium') |

#### `dim_stores`

| Column | Data Type |
|---|---|
| store_id | bigint |
| name | varchar |
| address | varchar |
| city | varchar |
| state | varchar |
| zip_code | varchar |
| category | varchar (e.g. 'produce', 'dairy', 'greek', 'italian') |

#### `fct_order`

| Column | Data Type |
|---|---|
| order_id (PK) | bigint |
| store_id (FK) | bigint |
| driver_id (FK) | bigint |
| user_id (FK) | bigint |
| order_type | varchar (e.g. 'pickup', 'delivery') |
| net_order_amount | decimal |
| cancelled_by | varchar (NULL if not cancelled) |
| date | date (partition) |

---

### Q1: What is the average order value ($) per user's city today?

```sql
SELECT
    u.city,
    ROUND(SUM(o.net_order_amount) / NULLIF(COUNT(o.order_id), 0), 2) AS avg_order_value
FROM fct_order o
JOIN dim_users u ON o.user_id = u.user_id
WHERE o.date = CURRENT_DATE
GROUP BY u.city
ORDER BY avg_order_value DESC;
```

---

### Q2: How many stores do more pickups than deliveries today?

```sql
WITH order_counts AS (
    SELECT
        store_id,
        SUM(CASE WHEN order_type = 'pickup' THEN 1 ELSE 0 END) AS pickup_count,
        SUM(CASE WHEN order_type = 'delivery' THEN 1 ELSE 0 END) AS delivery_count
    FROM fct_order
    WHERE date = CURRENT_DATE
    GROUP BY store_id
)
SELECT
    COUNT(*) AS stores_with_more_pickups
FROM order_counts
WHERE pickup_count > delivery_count;
```

**Alternative (using HAVING shorthand):**

```sql
WITH order_stats AS (
    SELECT
        store_id
    FROM fct_order
    WHERE date = CURRENT_DATE
    GROUP BY store_id
    HAVING SUM(CASE WHEN order_type = 'pickup' THEN 1 ELSE 0 END) > SUM(CASE WHEN order_type = 'delivery' THEN 1 ELSE 0 END)
)
SELECT COUNT(store_id) AS stores_with_more_pickups
FROM order_stats;
```

---

### Q3: What are the three most popular store categories in the last month? Popularity should be based on the number of customers who ordered from those stores. In addition to categories please also provide % share of revenue.

**Simple version (unique customers only):**

```sql
SELECT
    s.category,
    COUNT(DISTINCT o.user_id) AS unique_customers
FROM fct_order o
JOIN dim_stores s ON o.store_id = s.store_id
WHERE o.cancelled_by IS NULL
  AND o.date >= CURRENT_DATE - INTERVAL '1 month'
  AND o.date < CURRENT_DATE
GROUP BY s.category
ORDER BY unique_customers DESC
LIMIT 3;
```

**Extended version (with % share of revenue):**

```sql
WITH total_revenue AS (
    SELECT SUM(net_order_amount) AS total_revenue
    FROM fct_order
    WHERE cancelled_by IS NULL
      AND date >= CURRENT_DATE - INTERVAL '1 month'
      AND date < CURRENT_DATE
)
SELECT
    s.category,
    COUNT(DISTINCT o.user_id) AS unique_users,
    SUM(o.net_order_amount) AS category_revenue,
    ROUND(100.0 * SUM(o.net_order_amount) / tr.total_revenue, 2) AS revenue_percent_share
FROM fct_order o
JOIN dim_stores s ON o.store_id = s.store_id
CROSS JOIN total_revenue tr
WHERE o.cancelled_by IS NULL
  AND o.date >= CURRENT_DATE - INTERVAL '1 month'
  AND o.date < CURRENT_DATE
GROUP BY s.category, tr.total_revenue
ORDER BY unique_users DESC
LIMIT 3;
```

---

## Python Questions

### Q1: Delivery Time Estimation

We want to provide customers with an estimate of when their order will be delivered. We have driving time between locations and a delivery routing sequence. Use that data to create a map of order_id to an expected delivery time message in the format:

`"Order <order_id> is expected to be delivered at <time>."`

#### Given Data

You will be given a list of `routing_steps` with one of three actions:

- **TRAVEL** — The driver travels from the current location to the next location.
- **PICKUP** — The driver picks up an order at the current location.
- **DROPOFF** — The driver drops off the order at the current location.

#### Example 1 (Single Driver)

```python
routing_steps = [
    {"driver_id": 1, "action": "TRAVEL", "location_id": 2},
    {"driver_id": 1, "action": "PICKUP", "order_id": 1},
    {"driver_id": 1, "action": "TRAVEL", "location_id": 3},
    {"driver_id": 1, "action": "DROPOFF", "order_id": 1}
]
```

#### Example 2 (Multiple Drivers)

```python
travel_time = [
    [ 0, 10, 17, 23,  9, 13],
    [10,  0, 30, 25,  5, 25],
    [17, 30,  0, 10,  7, 33],
    [23, 25, 10,  0, 11, 35],
    [ 9,  5,  7, 11,  0, 27],
    [13, 25, 33, 35, 27,  0]
]

routing_steps = [
    {"driver_id": 1, "action": "TRAVEL", "location_id": 1},
    {"driver_id": 2, "action": "TRAVEL", "location_id": 3},
    {"driver_id": 1, "action": "PICKUP", "order_id": 1},
    {"driver_id": 1, "action": "TRAVEL", "location_id": 2},
    {"driver_id": 2, "action": "PICKUP", "order_id": 2},
    {"driver_id": 2, "action": "PICKUP", "order_id": 3},
    {"driver_id": 2, "action": "TRAVEL", "location_id": 4},
    {"driver_id": 2, "action": "PICKUP", "order_id": 4},
    {"driver_id": 1, "action": "DROPOFF", "order_id": 1},
    {"driver_id": 1, "action": "TRAVEL", "location_id": 5},
    {"driver_id": 2, "action": "DROPOFF", "order_id": 4},
    {"driver_id": 2, "action": "DROPOFF", "order_id": 2},
    {"driver_id": 2, "action": "TRAVEL", "location_id": 1},
    {"driver_id": 2, "action": "DROPOFF", "order_id": 3}
]
```

#### Expected Output

- Order 1 expected delivery time is 40
- Order 2 expected delivery time is 61
- Order 3 expected delivery time is 86
- Order 4 expected delivery time is 61

---

### Solution

```python
def calculate_delivery_times(routing_steps, travel_time):
    # Track current location and cumulative time for each driver
    driver_state = {}
    # Track delivery times for each order
    order_delivery_times = {}

    for step in routing_steps:
        driver_id = step["driver_id"]
        action = step["action"]

        # Initialize driver state if not exists (starts at location 0 with time 0)
        if driver_id not in driver_state:
            driver_state[driver_id] = {
                "current_location": 0,
                "current_time": 0
            }

        if action == "TRAVEL":
            location_id = step["location_id"]
            current_location = driver_state[driver_id]["current_location"]
            # Add travel time from current location to new location
            travel_duration = travel_time[current_location][location_id]
            driver_state[driver_id]["current_time"] += travel_duration
            driver_state[driver_id]["current_location"] = location_id

        elif action == "DROPOFF":
            order_id = step["order_id"]
            # Record the delivery time
            order_delivery_times[order_id] = driver_state[driver_id]["current_time"]

    return order_delivery_times


result = calculate_delivery_times(routing_steps, travel_time)
for order_id, delivery_time in sorted(result.items()):
    print(f"Order {order_id} expected delivery time is {delivery_time}")
```
