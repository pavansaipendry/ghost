# Set 3 — Uber Carpool

---

## Scenario

A rideshare service allows customers to use an app to request a driver to pick the customer up and drop them off at their destination. To reduce costs and the frequency of required trips, customers can select a 'carpool' option, which will overlap their route with other customers, resulting in an overall longer trip with multiple pick-ups and drop-offs.

Common considerations when a carpooling algorithm is deployed:

- Type of vehicle and maximum occupancy
- Historical demand of trips along original route
- Customer ratings
- Value proposition to customer (how much is carpooling incentivised)

We recently launched this carpool option in the last couple of months. The executives want to know if the option is increasing app usage, and if the value proposition passed along to the customer is high enough to encourage usage, without eating into the company's profits.

---

## Question 1: What business questions would help us understand the value proposition offered by the carpooling option?

---

### Rider
- Is the avg fare per trip decreased?
- Are users saving money with the new feature?
- Is the avg wait time similar to regular trips?
- Are users satisfied with the new feature?

### Driver
- Is idle time reduced?
- Have drivers' hourly earnings increased?
- Are drivers completing more trips?
- Is driver satisfaction higher or lower?

### Company
- Is the company generating more revenue with this new feature?
- Is the profit per trip increased?
- Are we gaining or losing riders/drivers?
- How has app engagement changed with this new feature?

---

## Question 2: List the metrics that would answer the business questions above. (10-12)

---

### Rider
- **Avg Fare Price Per Trip** — compare regular vs carpool rides *(avg(fare) grouped by ride_type)*
- **Avg Cost Savings per Carpool Trip** — how much cheaper carpool is vs regular *(avg(regular_fare - carpool_fare))*
- **NPS Score** — promoters minus detractors *(%promoters - %detractors)*
- **Rider Retention / Churn Rate** — riders still active over time *(returning riders / total riders) * 100*

### Driver
- **Avg Earnings per Hour** — total earnings divided by hours online *(total_earnings / hours_online)*
- **Avg Idle Time Between Rides** — time driver is waiting with no passenger *(avg(next_pickup_ts - last_dropoff_ts))*
- **Driver Retention Rate** — drivers still active over time *(returning drivers / total drivers) * 100*
- **Avg Weekly Earnings per Driver** — *(sum(earnings) / num_drivers) per week*

### Company
- **Revenue per Carpool Trip** — *(total_revenue / total_carpool_trips)*
- **Profit Margin** — *((revenue - cost) / revenue) * 100*
- **New User Sign-ups per Week** — drivers and riders separately *(count(new_signups) per week)*
- **Churn Rate** — drivers and riders *(churned users / total users) * 100*
- **Avg Carpool Trips per Ride** — *(total_carpool_trips / total_trips)*
- **Cancellation Rate** — pct of carpool bookings cancelled *(cancelled_bookings / total_carpool_bookings) * 100*
- **DAU / WAU / MAU** — daily, weekly, monthly active users
- **ARPU** — avg revenue per user *(total_revenue / total_active_users)*
- **Total Promotions Value — last 7 days** — total discount/promo amount given out

---

## Question 3: What are the most important dimensions / cuts relevant to these metrics?

---

### Driver / Rider
- Age
- Gender
- Sign-up Date
- Location (city, country)

### Vehicle
- Type
- Model
- Make
- Year
- Registration Expiry Date

### Ride Dimensions
- Trip Timeframe (short, medium, long)
- Number of Passengers
- Ride Type (regular, carpool)
- Number of Stops

### User Behaviour
- New vs Returning
- Ride Frequency

### Time Periods
- Time of Day
- Day of the Week
- Seasonality / Holiday

---

## Question 4: Design a data model to answer — how often is carpooling selected vs regular rides, what is the avg amount saved by the company through carpooling, and what is the avg cost passed on to the customer?

---

### Business Process

rider request → driver match → driver acceptance → pickup → ride → dropoff (or cancellation)

---

### Key Entities

- Rider
- Driver
- Vehicle
- Location
- Trip

---

### `dim_rider`

| Column | Notes |
|---|---|
| rider_id (PK) | |
| age | |
| gender | |
| signup_date | |
| city | |
| avg_rating_score | |
| date | Snapshot partitioned |

---

### `dim_driver`

| Column | Notes |
|---|---|
| driver_id (PK) | |
| age | |
| gender | |
| signup_date | |
| city | |
| avg_rating_score | |
| dl_number | Driver's licence number |
| date | Snapshot partitioned |

---

### `dim_vehicle`

| Column | Notes |
|---|---|
| vehicle_id (PK) | |
| type | |
| make | |
| model | |
| year | |
| capacity | |
| registration_expiry_date | |
| date | Snapshot partitioned |

---

### `dim_location`

| Column | Notes |
|---|---|
| location_id (PK) | |
| region | |
| city | |
| country | |
| state | |
| zip_code | |
| date | Snapshot partitioned |

---

### `fct_carpool_trips`

| Column | Notes |
|---|---|
| trip_id (PK) | |
| carpool_trip_id | Parent trip ID — groups riders sharing the same physical trip |
| driver_id (FK) | |
| rider_id (FK) | |
| pickup_location_id (FK) | |
| dropoff_location_id (FK) | |
| vehicle_id (FK) | |
| trip_placed_ts | |
| driver_acceptance_ts | |
| pickup_ts | |
| dropoff_ts | |
| regular_fare | What the ride would cost without carpool |
| carpool_fare | Actual fare charged |
| cancellation_reason | |
| cancelled_by | |
| ride_type | regular / carpool |
| date | Incrementally partitioned |

---

### Relationships

- `dim` → `fact`: 1:M — one driver/rider/vehicle can appear across many trips
- `fact` → `dim`: 1:1 — each trip row points to exactly one dim record per FK

---

## Follow-up Questions

### Q1: Why can Driver and Rider not be in a single table?

Drivers and riders have different attributes. Drivers have a `dl_number`, vehicle assignments, and earnings data that riders don't have. Putting them in one table means a lot of NULL columns for each side, messy queries, and harder access control. Keeping them separate makes the model cleaner.

---

### Q2: What if you wanted to find all drivers associated with a vehicle?

A vehicle can have multiple drivers, and a driver can drive multiple vehicles — this is a **M:M relationship**. There are two ways to model it:

**Option 1 — Store a list in `dim_vehicle`** (simpler, but harder to query):

#### Updated `dim_vehicle`
| Column | Notes |
|---|---|
| vehicle_id (PK) | |
| drivers | list of driver_ids |
| type | |
| make | |
| model | |
| year | |
| capacity | |
| registration_expiry_date | |

**Option 2 — Bridge table (preferred):**

#### `int_driver_vehicle` (M:M Bridge Table)
| Column | Notes |
|---|---|
| driver_vehicle_id (PK) | |
| driver_id (FK) | |
| vehicle_id (FK) | |
| assigned_date | |
| date | |

This lets you query all drivers for a vehicle and all vehicles for a driver cleanly without parsing a list.

#### Updated `fct_carpool_trips`
| Column | Notes |
|---|---|
| trip_id (PK) | |
| carpool_trip_id | Parent trip ID — groups riders sharing the same physical trip |
| driver_id (FK) | |
| rider_id (FK) | |
| pickup_location_id (FK) | |
| dropoff_location_id (FK) | |
| vehicle_id (FK) | |
| trip_placed_ts | |
| driver_acceptance_ts | |
| pickup_ts | |
| dropoff_ts | |
| cancellation_reason | |
| ride_type | regular / carpool |
| date | Incrementally partitioned |

---

### Q3: How do you know if a driver is acting as a customer and ordering?

A person can exist in both `dim_driver` and `dim_rider` as separate records with the same underlying identity. To link them, we'd add a `user_id` foreign key to both tables that maps back to a single `dim_user` table. If a driver places an order, they'd appear as a rider in `fct_carpool_trips` using their rider_id. The `user_id` linkage lets you identify when the same person is acting in both roles.

---

### Q4: What is the average wait time if a trip gets cancelled due to driver not arriving?

We already have `trip_placed_ts`, `driver_acceptance_ts`, and `cancellation_ts` in `fct_carpool_trips`. For trips cancelled because the driver didn't arrive, filter on `cancellation_reason = 'driver_no_show'` and calculate the time between when the trip was placed and when it was cancelled.

```sql
SELECT AVG(EXTRACT(EPOCH FROM (cancellation_ts - trip_placed_ts)) / 60) AS avg_wait_time_minutes
FROM fct_carpool_trips
WHERE cancellation_reason = 'driver_no_show';
```

---

### Q5: What is the frequency that the fct table gets updated?

The `fct_carpool_trips` table is **incrementally partitioned** by `date`. It gets updated in near real-time as trips are completed or cancelled — typically on an event-driven or micro-batch pipeline (every few minutes). For dashboards that don't need real-time data, a daily batch refresh is sufficient. The partition column ensures only new data is appended, not the full table rewritten.

---

### Q6: A delivery pool feature allows drivers to deliver food to multiple customers in a single order. How do you capture multiple orders as a single delivery pool order?

Use the `carpool_trip_id` (parent trip ID) pattern already in the model. Each delivery order gets its own `trip_id` row, but all orders sharing the same physical delivery run are linked via a shared `carpool_trip_id`. This is a 1:M relationship — one delivery pool trip → many individual order rows.

#### Updated `fct_carpool_trips` (delivery pool)
| Column | Notes |
|---|---|
| trip_id (PK) | One row per individual order/rider |
| carpool_trip_id (FK) | Parent ID — groups all orders in the same pool delivery run |
| driver_id (FK) | |
| rider_id (FK) | Customer who placed this order |
| pickup_location_id (FK) | Restaurant / pickup point |
| dropoff_location_id (FK) | Customer's delivery address |
| vehicle_id (FK) | |
| trip_placed_ts | |
| driver_acceptance_ts | |
| pickup_ts | |
| dropoff_ts | |
| regular_fare | |
| carpool_fare | |
| stop_sequence | Order of stops on this pool trip |
| cancellation_reason | |
| cancelled_by | |
| ride_type | regular / carpool |
| date | Incrementally partitioned |

---

### Q7: How do you calculate # regular orders vs # pool orders?

Using `ride_type` in `fct_carpool_trips`, group and count:

```sql
SELECT
    ride_type,
    COUNT(DISTINCT carpool_trip_id) AS total_trips,
    COUNT(trip_id) AS total_orders
FROM fct_carpool_trips
GROUP BY ride_type;
```

For pool, `COUNT(DISTINCT carpool_trip_id)` gives the number of unique physical trips, while `COUNT(trip_id)` gives the total individual orders within those trips.

---

### Q8: What is the cost saved by the customer due to the delivery pool feature?

Already captured via `regular_fare` and `carpool_fare` in `fct_carpool_trips`.

```sql
SELECT AVG(regular_fare - carpool_fare) AS avg_savings_per_carpool_order
FROM fct_carpool_trips
WHERE ride_type = 'carpool';
```

---

### Q9: How can we know the avg number of stops for delivery pool trips from the given model? If not, how do you change the model to answer this?

The base model doesn't directly track stops per pool trip. To answer this, we added a `stop_sequence` column to `fct_carpool_trips` (see Q6). With that, we can count the number of rows per `carpool_trip_id` to get the number of stops, then average across all pool trips:

```sql
SELECT AVG(stops_per_trip) AS avg_stops_per_pool_trip
FROM (
    SELECT carpool_trip_id, COUNT(trip_id) AS stops_per_trip
    FROM fct_carpool_trips
    WHERE ride_type = 'carpool'
    GROUP BY carpool_trip_id
) t;
```

---

### Q10: If we wanted to track performance without being impacted by the huge FCT table size, how do we do that?

Build a pre-aggregated table that rolls up the fact table daily. This avoids scanning millions of rows every time the dashboard queries.

#### `agg_rider_stats`
| Column | Notes |
|---|---|
| region | |
| vehicle_type | |
| age_group | |
| date | |
| avg_riders_per_hour | |
| total_trips | |
| total_carpool_trips | |
| avg_carpool_fare | |
| avg_regular_fare | |
| avg_savings | regular_fare - carpool_fare |

---

## SQL Questions

### Table Schemas

#### `fct_rides`

| Column | Data Type |
|---|---|
| ride_id | varchar |
| user_id | bigint |
| driver_id | bigint |
| vehicle_id | bigint |
| ride_type | varchar ('carpool' / 'regular') |
| region | varchar |
| start_time | timestamp |
| end_time | timestamp |
| date | date (partition) |

#### `dim_vehicles`

| Column | Data Type |
|---|---|
| vehicle_id | bigint |
| type | varchar |
| capacity | bigint |

---

### Q1: Ratio of carpool to all trips in last 30 days

```sql
SELECT
    COUNT(CASE WHEN ride_type = 'carpool' THEN ride_id ELSE NULL END) * 1.0 / NULLIF(COUNT(*), 0) AS ratio_carpool_trips
FROM fct_rides
WHERE date >= CAST(CURRENT_DATE - INTERVAL '30 days' AS VARCHAR);
```

---

### Q2: Rank vehicle types by most used for carpool, based on customer time spent in the vehicle

```sql
SELECT
    dim.type AS vehicle_type,
    COALESCE(SUM(EXTRACT(EPOCH FROM (fct.end_time - fct.start_time))), 0) AS time_spent_seconds
FROM dim_vehicles dim
LEFT JOIN (
    SELECT vehicle_id, start_time, end_time
    FROM fct_rides
    WHERE ride_type = 'carpool'
) fct ON dim.vehicle_id = fct.vehicle_id
GROUP BY dim.type
ORDER BY time_spent_seconds DESC;
```

---

### Q3: Number of drivers who made more pool rides than regular rides

```sql
WITH driver_stats AS (
    SELECT
        driver_id,
        SUM(CASE WHEN ride_type = 'carpool' THEN 1 ELSE 0 END) AS num_pool_rides,
        SUM(CASE WHEN ride_type = 'regular' THEN 1 ELSE 0 END) AS num_regular_rides
    FROM fct_rides
    GROUP BY driver_id
)
SELECT COUNT(DISTINCT driver_id) AS total_drivers
FROM driver_stats
WHERE num_pool_rides > num_regular_rides;
```

---

### Q4: Aggregate table powering a dashboard — ratio of carpool trips by region, vehicle type, and date

```sql
SELECT
    fct.region,
    dim.type AS vehicle_type,
    fct.date,
    ROUND(SUM(CASE WHEN fct.ride_type = 'carpool' THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS ratio_carpool_trips
FROM fct_rides fct
JOIN dim_vehicles dim ON fct.vehicle_id = dim.vehicle_id
GROUP BY GROUPING SETS (
    (fct.region, dim.type, fct.date),
    (fct.region, dim.type),
    (dim.type, fct.date),
    (fct.region, fct.date),
    (fct.region),
    (dim.type),
    (fct.date),
    ()
);
```

---

## Python Questions

### Q1: Given total passenger capacity in a vehicle and a list of booking requests, return True if all bookings can be fulfilled without exceeding capacity at any point, False otherwise

**Input:**

```python
# vehicle passenger capacity = 6

booking_requests = [
    {"request_id": 1, "pickup_time": 10, "drop_off_time": 20, "total_passengers": 3},
    {"request_id": 2, "pickup_time": 15, "drop_off_time": 25, "total_passengers": 2},
    {"request_id": 3, "pickup_time": 30, "drop_off_time": 40, "total_passengers": 2},
    {"request_id": 4, "pickup_time": 35, "drop_off_time": 45, "total_passengers": 3},
    {"request_id": 5, "pickup_time": 50, "drop_off_time": 60, "total_passengers": 4},
    {"request_id": 6, "pickup_time": 55, "drop_off_time": 65, "total_passengers": 4},
    {"request_id": 7, "pickup_time": 70, "drop_off_time": 80, "total_passengers": 5},
    {"request_id": 8, "pickup_time": 75, "drop_off_time": 85, "total_passengers": 3},
    {"request_id": 9, "pickup_time": 90, "drop_off_time": 100, "total_passengers": 1}
]
```

**Expected Output:** `False`

Requests 5 (4 passengers, t=50–60) and 6 (4 passengers, t=55–65) overlap — combined 8 passengers > capacity of 6.

**Solution:**

```python
def booking_process(booking_requests, capacity):
    events = []
    for request in booking_requests:
        pickup = request['pickup_time']
        dropoff = request['drop_off_time']
        passengers = request['total_passengers']
        events.append((pickup, passengers))
        events.append((dropoff, -passengers))

    # Sort by time; at same time, process dropoffs (-ve) before pickups (+ve)
    events.sort(key=lambda x: (x[0], x[1]))

    current_passengers = 0
    for time, count in events:
        current_passengers += count
        if current_passengers > capacity:
            return False
    return True

print(booking_process(booking_requests, capacity=6))  # False
```
