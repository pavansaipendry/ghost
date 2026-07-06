# Set 6 — Car Rental Expansion

---

## Scenario

We recently launched a car rental service. The app for this service allows customers to select a car size and rent a car (owned by the rental company) at the various rental locations available. Within the app, there is an interface for customers to browse car options and make reservations.

---

## Question 1: The leadership team wants to identify expansion opportunities for additional locations. What data would you look at to identify where to expand?

---

### Clarifying Questions

Before diving in, I'd want to ask a couple of things. First — are we an established brand like Enterprise or Hertz, or are we still relatively new? That changes the strategy a lot. And second — what's the goal here, is it revenue growth, capturing more market share, or are we trying to get into underserved markets? That'll shape which signals I prioritize.

*(write: Company context | Goal / objective)*

---

### Key Areas to Evaluate

Assuming we're aligned on those, I'd think about expansion across seven areas.

*(write: Demand | Supply | ROI | Competition | Geography | Customers | Regulatory)*

#### Demand *(write: Search data, conversion rate, distance to nearest location)*
The starting point is always — is there real demand somewhere we're not serving? I'd dig into our search and reservation data and look for places where we're getting a lot of searches but low conversions, or where customers are driving far out of their way to reach us. That gap is basically a customer telling us "I want this, just not here."

#### Supply *(write: Stockouts, utilization rate, one-way rental patterns)*
But before we get excited about demand, I'd sanity check our operations. Are we already struggling to keep cars available at existing locations? Frequent stockouts, high utilization, one-way rentals piling up in certain areas — those are signs demand exists but we may need to sort out fleet management before planting a flag somewhere new.

#### ROI *(write: ADR, real estate cost, discounting, payback period)*
Even if demand looks great, the economics have to work. I'd look at what daily rates we could realistically charge, what real estate costs look like, and whether we'd need to discount heavily just to compete. Ideally we want a market where we can charge premium rates, attach add-ons, and get to payback within 18 months or so.

#### Competition *(write: Competitor density, public transit, business / tourism travel)*
I'd also look at who's already there. A crowded market with five strong competitors and great public transit is a tough place to break in. But a market with weak competition, limited transit options, and growing business travel? That's the sweet spot.

#### Geographical Factors *(write: Neighbourhood growth, seasonality, access, demand generators)*
Then I'd zoom out and ask — is this location actually durable? A place that looks good today but has a declining neighbourhood, heavy seasonality, or bad access isn't a great long-term bet. I want to see proximity to airports, hotels, business districts, a stable or growing population, and ideally year-round demand.

#### Customers *(write: Repeat customers, loyalty, distance travelled to reach us)*
Our own customer data can be a goldmine here too. If I'm seeing pockets of repeat, high-loyalty customers who are regularly traveling a long distance to reach us — that's a pretty clear signal those areas want a location.

#### Regulatory Factors *(write: Permits, insurance, zoning)*
And lastly, before any of this becomes real, I'd make sure we've checked the regulatory side. Permitting, insurance requirements, zoning — these can completely block or delay an expansion, so it's worth validating early before committing budget.

---

### Getting Data for Expansion

Assuming you do not have any data, how do you go about getting it?

#### Scenario A — No Internal Data (New Markets)

When entering completely new markets, leverage external sources.

**Competitor Data**
- Scrape price listings from Hertz, Avis, Enterprise
- Use for revenue potential estimation

**Search and Demand Signals**
- Get data from Google Trends
- Validate real demand (e.g., "car rental near me" searches)

**Government and Public Data**
- US Census Bureau, airports, DMV registrations
- Size the market: population and income, airport passenger volume, vehicle ownership rates

**Third-Party Mobility Data**
- Purchase from third-party data providers
- Use for travel patterns, demographic data

**Partnership Data**
- Airlines, hotels, travel agencies
- Partner for data or referral programs

#### Scenario B — Limited Internal Data

When we have some internal data, we can still extract value.

**Sampling and Extrapolation**
- Internal app logs (search, bookings)
- Extrapolate from sample to estimate total demand

**Cohort Analysis**
- Historical data from similar cities or markets
- Identify comparable markets and apply their growth trajectory

**Proxy Metrics**
- App downloads, website visits, location searches
- Interest signals when booking data is sparse

**Confidence Intervals**
- Statistical modeling of sparse data
- Provide booking estimate ranges with upper and lower bounds

#### Scenario C — Primary Research

When secondary data is insufficient.

**Surveys**
- Target via digital ads, email campaigns, airport surveys
- Capture direct customer intent

**Focus Groups**
- Recruit target customers locally to get qualitative insights and pain points
- Understand why competitors succeed or fail

**Pilot or Soft Launch**
- Deploy a small fleet to gather real utilization data

**Geo-Targeted A/B Marketing**
- Run ads via Google Ads or Meta Ads
- Measure click-through and sign-up interest by region

**Local Partnerships**
- Partner with hotels and corporate offices to understand travel demand and referral volume

---

## Question 2: Our data show that certain rental car locations consistently rank in the top 5 in terms of revenue. What metrics would you look at to understand contributors to their success?

---

### Demand

- **Total Reservations** — total completed bookings in a period *(# of completed bookings)*
- **Search-to-Reserve Conversion** — ratio of bookings to qualified searches *(bookings / searches)*
- **Booking Lead Time** — how far in advance customers book; longer lead time signals strong planned demand *(booking date - reservation date)*
- **Median Time to Book** — time between first search and confirmed reservation *(median of confirmed_ts - first_search_ts)*

### Supply

- **Fleet Utilization Rate** — percentage of car-days actually rented *(rented car-days / total available car-days) * 100*
- **Maintenance Turnaround Time** — time between car return and rent-ready *(rent_ready_ts - return_ts)*
- **Fleet-to-Rental Ratio** — proportion of fleet that's rentable *(rentable cars / total fleet)*
- **Occupancy Rate** — percentage of fleet booked at the moment *(cars currently rented / total fleet) * 100*
- **Average Wait Time** — time between reservation and pick-up *(avg of pickup_ts - reservation_ts)*

### Revenue

- **ADR (Avg Daily Rate)** — revenue per rental day *(total revenue / total rental days)*
- **Add-on Attach Rate** — percentage of reservations with extras (insurance, GPS, etc.) *(reservations with add-ons / total reservations) * 100*
- **Avg Booking Value** — total revenue per booking *(total revenue / total bookings)*
- **Rental Rate** — revenue per number of bookings *(total revenue / # of bookings)*

### Customer Metrics

- **Repeat Rate** — percentage of customers rebooking in timeframe (30, 60, 90 days) *(customers with 2+ bookings / total unique customers) * 100*
- **NPS** — promoters minus detractors *( % promoters - % detractors)*
- **Customer Retention Rate** — percentage of customers active over time *(returning customers / total customers at start of period) * 100*
- **Customer Satisfaction Score (CSAT)** — average satisfaction rating per rental *(sum of ratings / total responses)*

### Profitability

- **Rental Revenue Per Vehicle** — average revenue generated per vehicle *(total revenue / total vehicles)*
- **Dollar Utilization** — annual revenue divided by fleet acquisition cost *(annual revenue / fleet acquisition cost)*
- **Net Profit Margin** — (revenue minus cost) divided by revenue *((revenue - cost) / revenue) * 100*

---

## Question 3: We want to build a dashboard that shows the most critical information to the leadership team for our car rental business. What steps would you follow? Describe your end-to-end workflow.

---

### Clarifying Questions

- Who is the audience?
- What decisions will they drive?
- What cadence are we expecting?

### Workflow: Align, Build, Launch

**1. Requirement Alignment**
- Understand what decisions leadership needs to make — expansion, pricing tweaks, or operational monitoring

**2. Understanding Audience**
- Map users: executives want high-level KPIs, analysts want drill-downs. Tailor the complexity accordingly

**3. KPI Framework and Thresholds**
- Pick 5–7 key metrics, adding color-coded thresholds so leaders can glance and see what requires attention

**4. Data Source Mapping**
- List all sources: reservations, fleet, pricing, customer feedback. Identify gaps and plan how to collect missing data

**5. Data Modeling**
- Build clean schemas with fact tables and dimension tables, and pre-compute daily aggregates for fast queries

**6. ETL/ELT Pipelines**
- Design incremental pipelines with retry logic and backfill capability

**7. Data Quality Controls**
- Implement checks like data freshness, record counts, business logic validation, and trigger alerts

**8. Visualization and Dashboard Design**
- Top: summary KPIs. Middle: trend lines. Bottom: drill-down filters. Keep it clean — max 7 metrics per screen. Use maps and funnels where helpful

**9. QA, Rollout, and Documentation**
- Validate against source data. Dry run with leadership. Document KPI definitions, user guidance, and access controls

**10. Iteration and Feedback Loop**
- Gather feedback and iterate or update based on new needs and data insights

---

## Question 4: Design a data model for the car rental system. What are the essential entities, their key attributes, and the relationships between them?

---

### Business Process

customer signup/login → search → car selection → book → pay → pick up → drive → return (or cancellation)

---

### Key Entities

- Users
- Vehicles
- Locations
- Reservations

---

### `dim_user`

| Column | Notes |
|---|---|
| user_id (PK) | |
| name | |
| gender | |
| age | |
| email | |
| city | |
| state | |
| country | |
| registration_ts | |
| loyalty_status | |
| last_active_ts | |
| date | Snapshot partitioned |

---

### `dim_vehicle`

| Column | Notes |
|---|---|
| vehicle_id (PK) | |
| make | |
| model | |
| year | |
| brand | |
| license_plate | |
| capacity | |
| vehicle_type | |
| fuel_type | |
| insurance_expiry | |
| date | Snapshot partitioned |

---

### `dim_location`

| Column | Notes |
|---|---|
| location_id (PK) | |
| latitude | |
| longitude | |
| city | |
| state | |
| zip | |
| country | |
| location_type | |
| date | Snapshot partitioned |

---

### `fct_reservation`

| Column | Notes |
|---|---|
| reservation_id (PK) | |
| user_id (FK) | |
| vehicle_id (FK) | |
| pick_up_location_id (FK) | |
| drop_off_location_id (FK) | |
| reservation_type | |
| reservation_channel | mobile / web |
| reservation_request_ts | |
| reservation_confirmed_ts | |
| pick_up_ts | |
| return_ts | |
| expected_return_ts | |
| pick_up_odometer | |
| drop_off_odometer | |
| total_distance_traveled | |
| payment_method_id | |
| fare_amount | |
| reservation_status | |
| canceled_by | |
| cancelled_ts | |
| date | Incrementally partitioned |

### Relationships

- `dim` → `fact`: 1:M (one user/vehicle/location can appear in many reservations)
- `fact` → `dim`: 1:1 (each reservation row points to exactly one dim record per FK)

---

## Question 5 (Extension): For each reservation, if you want to store additional drivers-related information, how would you do it?

---

### Option 1 — Nested in Fact Table
- Store additional drivers as a list or JSON/map column directly in `fct_reservation`
- Simple but harder to query individual driver attributes

### Option 2 — Bridge Table (M:M)

1 reservation → multiple additional drivers (1:M)
1 driver → multiple reservations (1:M)
Overall relationship is **M:M** — resolved using a bridge table

#### `fct_reserve_drivers`

| Column | Notes |
|---|---|
| reservation_id (FK) | |
| user_id (FK) | |
| driver_id (PK) | |
| driver_name | |
| driver_dl | Driver's license number |

---

## SQL Questions

### Table Schemas

#### `dim_cars`

| Column | Data Type |
|---|---|
| car_id (PK) | bigint |
| make | varchar |
| model | varchar |
| year | int |
| size | varchar |
| license_plate_number | varchar |
| location_id (FK) | bigint |

#### `dim_locations`

| Column | Data Type |
|---|---|
| location_id (PK) | bigint |
| address | varchar |
| city | varchar |
| state | varchar |
| zip | varchar |
| country | varchar |
| type | varchar |

#### `dim_users`

| Column | Data Type |
|---|---|
| user_id (PK) | bigint |
| name | varchar |
| email | varchar |
| license_number | varchar |
| license_state | varchar |

#### `fct_rentals`

| Column | Data Type |
|---|---|
| rental_id (PK) | bigint |
| user_id (FK) | bigint |
| car_id (FK) | bigint |
| pick_up_location_id (FK) | bigint |
| drop_off_location_id (FK) | bigint |
| pick_up_time | timestamp |
| drop_off_time | timestamp |
| rate_per_day | decimal |

---

### Q1: Rental metrics for pickups in California last year by car size

Number of rentals, number of unique users, and ratio of rentals per unique user.

```sql
SELECT
    c.size AS car_size,
    COUNT(r.rental_id) AS number_of_rentals,
    COUNT(DISTINCT r.user_id) AS number_of_unique_users,
    ROUND(COUNT(r.rental_id) * 1.0 / NULLIF(COUNT(DISTINCT r.user_id), 0), 2) AS ratio_rentals_per_user
FROM fct_rentals r
INNER JOIN dim_cars c ON r.car_id = c.car_id
INNER JOIN dim_locations l ON r.pick_up_location_id = l.location_id
WHERE l.state = 'CA'
  AND YEAR(r.pick_up_time) = YEAR(CURRENT_DATE) - 1
GROUP BY c.size
ORDER BY number_of_rentals DESC;
```

---

### Q2: Utilization rate per location and car size for today

All rental pickups and drop-offs happen at the car's home location, and cars are part of that home location's inventory (`location_id` in `dim_cars`).

**Formula:** Utilization Rate = Number of Cars Rented / Number of Cars in Location

```sql
WITH currently_rented AS (
    SELECT
        c.location_id,
        c.size,
        COUNT(DISTINCT r.car_id) AS cars_rented_today
    FROM fct_rentals r
    INNER JOIN dim_cars c ON r.car_id = c.car_id
    WHERE CURRENT_DATE BETWEEN DATE(r.pick_up_time) AND DATE(r.drop_off_time)
    GROUP BY c.location_id, c.size
),
total_inventory AS (
    SELECT
        location_id,
        size,
        COUNT(car_id) AS total_cars
    FROM dim_cars
    GROUP BY location_id, size
)
SELECT
    l.city,
    l.state,
    i.location_id,
    i.size,
    COALESCE(cr.cars_rented_today, 0) AS cars_rented_today,
    i.total_cars,
    ROUND(COALESCE(cr.cars_rented_today, 0) * 100.0 / NULLIF(i.total_cars, 0), 2) AS utilization_rate_pct
FROM total_inventory i
LEFT JOIN currently_rented cr ON i.location_id = cr.location_id AND i.size = cr.size
INNER JOIN dim_locations l ON i.location_id = l.location_id
ORDER BY l.city, i.size;
```

---

## Python Questions

### Q1: Car Booking Manager

Our rental location has only one car. Given an ordered dictionary of rental orders, create a function that assigns the car to each order or rejects it if it overlaps with an already accepted booking.

**Input:**

```python
rental_orders_by_id = {
    21: {"pickup_date": "2025-03-01", "dropoff_date": "2025-03-07"},
    22: {"pickup_date": "2025-03-10", "dropoff_date": "2025-03-13"},
    23: {"pickup_date": "2025-03-01", "dropoff_date": "2025-03-11"},
    24: {"pickup_date": "2025-03-08", "dropoff_date": "2025-03-28"},
    25: {"pickup_date": "2025-02-15", "dropoff_date": "2025-02-25"},
    26: {"pickup_date": "2025-02-27", "dropoff_date": "2025-02-28"},
    27: {"pickup_date": "2025-03-10", "dropoff_date": "2025-03-31"},
    28: {"pickup_date": "2025-03-13", "dropoff_date": "2025-03-30"},
    29: {"pickup_date": "2025-03-14", "dropoff_date": "2025-03-30"},
}
```

**Expected Output:**

- Order 21 ok
- Order 22 ok
- Order 23 rejected
- Order 24 rejected
- Order 25 ok
- Order 26 ok
- Order 27 rejected
- Order 28 rejected
- Order 29 ok

**Solution:**

```python
from datetime import datetime

def process_bookings(rental_orders_by_id):
    accepted_bookings = []

    for order_id, booking in rental_orders_by_id.items():
        start_time = datetime.strptime(booking["pickup_date"], "%Y-%m-%d")
        end_time = datetime.strptime(booking["dropoff_date"], "%Y-%m-%d")

        is_overlap = False
        for accepted in accepted_bookings:
            if start_time <= accepted["end_time"] and end_time >= accepted["start_time"]:
                is_overlap = True
                break

        if is_overlap:
            print(f"Order {order_id} rejected")
        else:
            print(f"Order {order_id} ok")
            accepted_bookings.append({
                "start_time": start_time,
                "end_time": end_time
            })

process_bookings(rental_orders_by_id)
```

---

### Q1 (Extended): Car Booking Manager with datetime format

Same problem with datetime strings in `"YYYY-MM-DD HH:MM:SS"` format and booking IDs 1–N.

**Input:**

```python
single_car_bookings_plan = {
    1: {"start_time": "2025-06-24 10:00:00", "end_time": "2025-06-24 11:00:00"},
    2: {"start_time": "2025-06-24 11:30:00", "end_time": "2025-06-24 12:30:00"},
    3: {"start_time": "2025-06-24 10:00:00", "end_time": "2025-06-24 10:30:00"},
    4: {"start_time": "2025-06-24 13:00:00", "end_time": "2025-06-24 14:00:00"},
    5: {"start_time": "2025-06-24 14:30:00", "end_time": "2025-06-24 15:30:00"},
    6: {"start_time": "2025-06-24 15:00:00", "end_time": "2025-06-24 16:00:00"},
    7: {"start_time": "2025-06-24 10:00:00", "end_time": "2025-06-24 11:15:00"},
    8: {"start_time": "2025-06-24 16:30:00", "end_time": "2025-06-24 17:30:00"}
}
```

**Expected Output:**

- Booking 1 ok
- Booking 2 ok
- Booking 3 rejected
- Booking 4 ok
- Booking 5 ok
- Booking 6 rejected
- Booking 7 rejected
- Booking 8 ok

**Solution:**

```python
from datetime import datetime

def manage_car_bookings(single_car_bookings_plan):
    accepted_bookings = []

    for booking_id in sorted(single_car_bookings_plan.keys()):
        booking = single_car_bookings_plan[booking_id]
        start_time = datetime.strptime(booking["start_time"], "%Y-%m-%d %H:%M:%S")
        end_time = datetime.strptime(booking["end_time"], "%Y-%m-%d %H:%M:%S")

        is_overlap = False
        for accepted in accepted_bookings:
            if start_time <= accepted["end_time"] and end_time >= accepted["start_time"]:
                is_overlap = True
                break

        if is_overlap:
            print(f"Booking {booking_id} rejected")
        else:
            print(f"Booking {booking_id} ok")
            accepted_bookings.append({
                "start_time": start_time,
                "end_time": end_time
            })

manage_car_bookings(single_car_bookings_plan)
```
