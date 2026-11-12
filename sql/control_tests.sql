-- Control test queries (SQLite). Each query returns one row per exception.
-- Parameters are bound by name from config/controls.json.

-- name: CTL-01
-- Dual approval above the high-value threshold: two approvers, both populated and distinct.
SELECT txn_id, card_id, amount, txn_timestamp, initiated_by, approver_1, approver_2,
       CASE
         WHEN approver_1 IS NULL OR approver_2 IS NULL THEN 'Second approval missing'
         ELSE 'Same person recorded as both approvers'
       END AS exception_detail
FROM transactions
WHERE status = 'APPROVED'
  AND amount > :threshold_inr
  AND (approver_1 IS NULL OR approver_2 IS NULL OR approver_1 = approver_2);

-- name: CTL-02
-- Segregation of duties: the initiator must not appear as an approver.
SELECT txn_id, card_id, amount, txn_timestamp, initiated_by, approver_1, approver_2,
       'Initiator ' || initiated_by || ' also approved the transaction' AS exception_detail
FROM transactions
WHERE initiated_by = approver_1
   OR (approver_2 IS NOT NULL AND initiated_by = approver_2);

-- name: CTL-03
-- Credit limit breach: an approved transaction must not push the balance over the limit.
SELECT txn_id, card_id, amount, txn_timestamp, balance_before, credit_limit,
       ROUND(balance_before + amount - credit_limit, 2) AS excess_over_limit,
       'Approved Rs. ' || printf('%.2f', balance_before + amount - credit_limit) || ' over limit' AS exception_detail
FROM transactions
WHERE status = 'APPROVED'
  AND balance_before + amount > credit_limit;

-- name: CTL-04
-- Duplicate transactions: same card, merchant and amount within the window of the previous one.
WITH ordered AS (
  SELECT txn_id, card_id, merchant_id, amount, txn_timestamp, epoch, status,
         LAG(txn_id) OVER w AS prev_txn_id,
         LAG(epoch)  OVER w AS prev_epoch
  FROM transactions
  WHERE status = 'APPROVED'
  WINDOW w AS (PARTITION BY card_id, merchant_id, amount ORDER BY epoch, txn_id)
)
SELECT txn_id, card_id, merchant_id, amount, txn_timestamp, prev_txn_id AS original_txn_id,
       epoch - prev_epoch AS seconds_after_original,
       'Duplicate of ' || prev_txn_id || ' after ' || (epoch - prev_epoch) || 's' AS exception_detail
FROM ordered
WHERE prev_epoch IS NOT NULL
  AND epoch - prev_epoch <= :window_seconds;
