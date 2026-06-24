-- Business question: How many individual process events exist in each region?
SELECT
    region,
    COUNT(*) AS event_count
FROM event_log
GROUP BY region
ORDER BY event_count DESC;

-- Business question: How many distinct order cases exist in each region?
SELECT
    region,
    COUNT(DISTINCT case_id) AS case_count
FROM event_log
GROUP BY region
ORDER BY case_count DESC;

-- Business question: What is the average order quantity in each region?
SELECT
    region,
    ROUND(AVG(quantity), 2) AS average_quantity
FROM event_log
GROUP BY region
ORDER BY average_quantity DESC;

-- Business question: How many distinct high-priority orders exist in each region?
SELECT
    region,
    COUNT(DISTINCT case_id) AS high_priority_order_count
FROM event_log
WHERE is_high_priority = 1
GROUP BY region
ORDER BY high_priority_order_count DESC;

-- Business question: Which process activities occur most frequently?
SELECT
    activity,
    COUNT(*) AS occurrence_count
FROM event_log
GROUP BY activity
ORDER BY occurrence_count DESC, activity;

-- Business question: Which customers have created the most distinct orders?
SELECT
    customer,
    COUNT(DISTINCT case_id) AS order_count
FROM event_log
GROUP BY customer
ORDER BY order_count DESC, customer
LIMIT 10;
