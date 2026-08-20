# Data Sources

## Official Prasarana GTFS static feed

- Endpoint: `https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl`
- Role: station, route, trip, and scheduled stop facts
- Status: verified and parsed on 2026-08-20
- Result: 1 Kelana Jaya route and 37 stations
- Limitation: does not contain passenger counts

## Official realtime feed

- Documentation: `https://developer.data.gov.my/realtime-api/gtfs-realtime`
- Role: possible future vehicle positions
- Status: not used for Kelana Jaya status
- Limitation: the documentation states the `rapid-rail-kl` realtime feed is not yet stable

## Historical ridership

- Current source: `data/external/demo_ridership.csv`
- Status: synthetic demonstration data only
- Required replacement: a lawful public dataset with station, date, hour, and passenger count
- Upload template: `historical_ridership_template.csv`

## Public reports

- Current source: manual controls or uploaded CSV
- Status: signals only, never official facts
- Required columns: `text`, `observed_at`
- Optional columns: `author_id`, `source`, `station`
- Upload template: `public_reports_template.csv`
