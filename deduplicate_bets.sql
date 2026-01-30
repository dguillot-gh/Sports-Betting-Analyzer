-- Deduplicate bets based on sport, stake, odds, and game_date
WITH cte AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY sport, stake, odds, game_date, sportsbook, description
               ORDER BY id
           ) as row_num
    FROM bets
)
DELETE FROM bets
WHERE id IN (
    SELECT id FROM cte WHERE row_num > 1
);

-- Check row count after deduplication
SELECT count(*) FROM bets;
