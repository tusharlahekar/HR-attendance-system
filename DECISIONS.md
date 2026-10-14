# DECISIONS.md

1. **Indexes**: I created a Compound Unique Index on `attendance_logs (emp_code, date)` to enforce R1 and prevent duplicate punch-ins. I also indexed `employees.department` and `attendance_logs.date` to ensure analytics stay fast at 100k+ records.
2. **Punch-in race**: By using a Unique Index, the database handles the race. The first request succeeds; the second throws a `DuplicateKeyError`. My code catches this and returns a 409, ensuring consistency without slow locks.
3. **Ties**: The leaderboard uses the `$rank` window function. If two people tie for Rank 2, they both appear as 2. The next person is 4. If the limit is 3, all 4 people are returned because their rank is <= 3.
4. **Headcount**: The department summary starts with the `employees` collection (the "left" side) and joins logs. This ensures employees with zero logs are included in the headcount (R9).
5. **100x Data**: I would implement an "Attendance Aggregator" that pre-calculates daily metrics into a summary collection at midnight. This would make trend queries O(1) instead of O(N).