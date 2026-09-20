-- ====================================================
-- NexaBank - Final Corrected MySQL Database Schema
-- Features:
-- 1. Customer, Manager, Staff accounts
-- 2. Customer approval by Staff and Manager
-- 3. One customer email can own Savings + Current accounts
-- 4. Direct deposits and withdrawals with transaction reference + IST date/time
-- 5. Fund transfers with From/To account and customer names
-- 6. Loan approval by Manager with approved date/time and clear-by date
-- 7. Fixed Deposit with Manager approval, deposited date/time and maturity date
-- 8. FD interest slabs for different time periods
-- 9. Views, stored procedure, minimum balance trigger
-- ====================================================

DROP DATABASE IF EXISTS nexabank_db;
CREATE DATABASE nexabank_db;
USE nexabank_db;

-- Keep MySQL session in Indian Standard Time
SET time_zone = '+05:30';

-- ====================================================
-- TABLE 1: ADMINS / BANK USERS
-- Stores Manager and Staff registrations.
-- ====================================================
CREATE TABLE admins (
    admin_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(15) NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    branch VARCHAR(120) DEFAULT 'Main Branch',
    role ENUM('manager','staff') NOT NULL,
    status ENUM('active','inactive') DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_admin_role (role),
    INDEX idx_admin_email (email)
);

-- ====================================================
-- TABLE 2: CUSTOMERS
-- One email = one customer identity.
-- Same customer can create multiple accounts in accounts table.
-- ====================================================
CREATE TABLE customers (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(15) NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    dob DATE NOT NULL,
    address TEXT NOT NULL,
    kyc_status ENUM('pending','verified','rejected','under_review') DEFAULT 'pending',

    staff_approval ENUM('pending','accepted','rejected') DEFAULT 'pending',
    manager_approval ENUM('pending','accepted','rejected') DEFAULT 'pending',
    approval_status ENUM('pending','approved','rejected') DEFAULT 'pending',

    assigned_staff_id INT NULL,
    approved_by_manager_id INT NULL,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_customer_staff
        FOREIGN KEY (assigned_staff_id) REFERENCES admins(admin_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_customer_manager
        FOREIGN KEY (approved_by_manager_id) REFERENCES admins(admin_id)
        ON DELETE SET NULL,

    INDEX idx_customer_email (email),
    INDEX idx_customer_approval (approval_status),
    INDEX idx_customer_staff_approval (staff_approval),
    INDEX idx_customer_manager_approval (manager_approval)
);

-- ====================================================
-- TABLE 3: ACCOUNTS
-- One customer can have one savings and one current account.
-- This is the correct fix for same-email savings/current feature.
-- ====================================================
CREATE TABLE accounts (
    account_id INT AUTO_INCREMENT PRIMARY KEY,
    account_number VARCHAR(20) NOT NULL UNIQUE,
    customer_id INT NOT NULL,
    account_type ENUM('savings','current') NOT NULL DEFAULT 'savings',
    balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    branch VARCHAR(100) DEFAULT 'Main Branch',
    interest_rate DECIMAL(5,2) DEFAULT 3.50,
    status ENUM('active','inactive','frozen','closed') DEFAULT 'inactive',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_acc_customer
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        ON DELETE RESTRICT,

    UNIQUE KEY uq_customer_account_type (customer_id, account_type),
    INDEX idx_acc_number (account_number),
    INDEX idx_acc_customer (customer_id),
    INDEX idx_acc_status (status)
);

-- ====================================================
-- TABLE 4: TRANSACTIONS
-- Direct deposits/withdrawals and all transaction history.
-- created_at follows current MySQL session time_zone (+05:30 IST).
-- ====================================================
CREATE TABLE transactions (
    transaction_id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_ref VARCHAR(40) NOT NULL UNIQUE,
    account_id INT NOT NULL,
    transaction_type ENUM(
        'deposit',
        'withdrawal',
        'transfer_in',
        'transfer_out',
        'interest',
        'fee',
        'loan_credit',
        'emi_payment',
        'fd_debit',
        'fd_maturity_credit'
    ) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    balance_after DECIMAL(15,2) NOT NULL,
    description VARCHAR(255),
    reference_account VARCHAR(20),
    transfer_mode ENUM('NEFT','RTGS','IMPS','UPI') DEFAULT NULL,
    status ENUM('pending','completed','failed','reversed') DEFAULT 'completed',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_tx_account
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        ON DELETE RESTRICT,

    INDEX idx_tx_ref (transaction_ref),
    INDEX idx_tx_account (account_id),
    INDEX idx_tx_created (created_at),
    INDEX idx_tx_type (transaction_type)
);

-- ====================================================
-- TABLE 5: LOANS
-- Manager approval, approved time, disbursed time, clear-by date.
-- ====================================================
CREATE TABLE loans (
    loan_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    account_id INT NULL,
    loan_type ENUM('personal','home','education','vehicle','gold') NOT NULL,
    principal_amount DECIMAL(15,2) NOT NULL,
    interest_rate DECIMAL(5,2) NOT NULL,
    tenure_months INT NOT NULL,
    emi_amount DECIMAL(15,2) NOT NULL,
    total_payable DECIMAL(15,2) DEFAULT 0.00,
    outstanding DECIMAL(15,2) NOT NULL,
    emi_paid_count INT DEFAULT 0,
    disbursed_on DATE,
    approved_at DATETIME NULL,
    loan_clear_date DATE NULL,
    next_emi_date DATE,
    status ENUM('applied','approved','active','closed','defaulted','rejected') DEFAULT 'applied',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_loan_customer
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_loan_account
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        ON DELETE SET NULL,

    INDEX idx_loan_customer (customer_id),
    INDEX idx_loan_account (account_id),
    INDEX idx_loan_status (status),
    INDEX idx_loan_type (loan_type),
    INDEX idx_loan_clear_date (loan_clear_date)
);

-- ====================================================
-- TABLE 6: BENEFICIARIES
-- ====================================================
CREATE TABLE beneficiaries (
    beneficiary_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    benef_name VARCHAR(120) NOT NULL,
    benef_acc_no VARCHAR(20) NOT NULL,
    bank_name VARCHAR(100) DEFAULT 'NexaBank',
    ifsc_code VARCHAR(15),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_benef_customer
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        ON DELETE RESTRICT,

    UNIQUE KEY uq_benef (customer_id, benef_acc_no),
    INDEX idx_benef_customer (customer_id)
);

-- ====================================================
-- TABLE 7: FIXED DEPOSITS
-- Customer applies FD; Manager approves/rejects.
-- Amount is deducted only after manager approval.
-- applied_at = request/deposit application date/time
-- approved_at = manager approval date/time
-- maturity_date = FD maturity date
-- ====================================================
CREATE TABLE fixed_deposits (
    fd_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    account_id INT NOT NULL,
    principal_amount DECIMAL(15,2) NOT NULL,
    tenure_months INT NOT NULL,
    interest_rate DECIMAL(5,2) NOT NULL,
    maturity_amount DECIMAL(15,2) NOT NULL,
    status ENUM('applied','approved','rejected','closed','matured') DEFAULT 'applied',
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at DATETIME NULL,
    maturity_date DATE NULL,

    CONSTRAINT fk_fd_customer
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_fd_account
        FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        ON DELETE RESTRICT,

    INDEX idx_fd_customer (customer_id),
    INDEX idx_fd_account (account_id),
    INDEX idx_fd_status (status),
    INDEX idx_fd_maturity_date (maturity_date)
);

-- ====================================================
-- TABLE 8: FD RATE SLABS
-- ====================================================
CREATE TABLE fd_rate_slabs (
    slab_id INT AUTO_INCREMENT PRIMARY KEY,
    min_months INT NOT NULL,
    max_months INT NULL,
    interest_rate DECIMAL(5,2) NOT NULL,
    description VARCHAR(100) NOT NULL
);

INSERT INTO fd_rate_slabs (min_months, max_months, interest_rate, description) VALUES
(3, 6, 4.50, '3 to 6 months'),
(7, 12, 5.50, '7 to 12 months'),
(13, 24, 6.25, '13 to 24 months'),
(25, 36, 6.75, '25 to 36 months'),
(37, 60, 7.25, '37 to 60 months'),
(61, NULL, 7.50, 'Above 60 months');

-- ====================================================
-- VIEW 1: CUSTOMER SUMMARY
-- ====================================================
CREATE OR REPLACE VIEW v_customer_summary AS
SELECT
    c.customer_id,
    c.full_name,
    c.email,
    c.phone,
    c.kyc_status,
    c.staff_approval,
    c.manager_approval,
    c.approval_status,
    COUNT(a.account_id) AS total_accounts,
    COALESCE(SUM(a.balance), 0) AS total_balance
FROM customers c
LEFT JOIN accounts a ON c.customer_id = a.customer_id
GROUP BY
    c.customer_id,
    c.full_name,
    c.email,
    c.phone,
    c.kyc_status,
    c.staff_approval,
    c.manager_approval,
    c.approval_status;

-- ====================================================
-- VIEW 2: TRANSACTION LEDGER
-- Includes From/To names using reference_account.
-- ====================================================
CREATE OR REPLACE VIEW v_transaction_ledger AS
SELECT
    t.transaction_id,
    t.transaction_ref,
    c.customer_id,
    c.full_name AS customer_name,
    c.email AS customer_email,
    a.account_number,
    a.account_type,
    t.transaction_type,
    t.amount,
    t.balance_after,
    t.description,
    t.reference_account,
    rc.full_name AS reference_customer_name,
    rc.email AS reference_customer_email,
    t.transfer_mode,
    t.status,
    t.created_at
FROM transactions t
JOIN accounts a ON t.account_id = a.account_id
JOIN customers c ON a.customer_id = c.customer_id
LEFT JOIN accounts ra ON t.reference_account = ra.account_number
LEFT JOIN customers rc ON ra.customer_id = rc.customer_id
ORDER BY t.created_at DESC;

-- ====================================================
-- VIEW 3: PENDING CUSTOMER APPROVALS
-- ====================================================
CREATE OR REPLACE VIEW v_pending_customer_approvals AS
SELECT
    c.customer_id,
    c.full_name,
    c.email,
    c.phone,
    c.dob,
    c.address,
    c.staff_approval,
    c.manager_approval,
    c.approval_status,
    a.account_number,
    a.account_type,
    a.balance,
    a.status AS account_status,
    c.created_at
FROM customers c
JOIN accounts a ON c.customer_id = a.customer_id
WHERE c.approval_status = 'pending'
ORDER BY c.created_at DESC;

-- ====================================================
-- VIEW 4: FIXED DEPOSIT SUMMARY
-- ====================================================
CREATE OR REPLACE VIEW v_fixed_deposit_summary AS
SELECT
    fd.fd_id,
    c.customer_id,
    c.full_name AS customer_name,
    c.email,
    a.account_number,
    fd.principal_amount,
    fd.tenure_months,
    fd.interest_rate,
    fd.maturity_amount,
    fd.status,
    fd.applied_at,
    fd.approved_at,
    fd.maturity_date
FROM fixed_deposits fd
JOIN customers c ON fd.customer_id = c.customer_id
JOIN accounts a ON fd.account_id = a.account_id
ORDER BY fd.applied_at DESC;

-- ====================================================
-- VIEW 5: LOAN SUMMARY
-- ====================================================
CREATE OR REPLACE VIEW v_loan_summary AS
SELECT
    l.loan_id,
    c.customer_id,
    c.full_name AS customer_name,
    c.email,
    a.account_number,
    l.loan_type,
    l.principal_amount,
    l.interest_rate,
    l.tenure_months,
    l.emi_amount,
    l.total_payable,
    l.outstanding,
    l.status,
    l.created_at,
    l.approved_at,
    l.disbursed_on,
    l.loan_clear_date,
    l.next_emi_date
FROM loans l
JOIN customers c ON l.customer_id = c.customer_id
LEFT JOIN accounts a ON l.account_id = a.account_id
ORDER BY l.created_at DESC;

-- ====================================================
-- STORED PROCEDURES
-- ====================================================
DELIMITER $$

CREATE PROCEDURE sp_account_statement(
    IN p_acc_no VARCHAR(20),
    IN p_from DATE,
    IN p_to DATE
)
BEGIN
    SELECT
        t.transaction_id,
        t.transaction_ref,
        t.transaction_type,
        t.amount,
        t.balance_after,
        t.description,
        t.reference_account,
        rc.full_name AS reference_customer_name,
        t.transfer_mode,
        t.created_at
    FROM transactions t
    JOIN accounts a ON t.account_id = a.account_id
    LEFT JOIN accounts ra ON t.reference_account = ra.account_number
    LEFT JOIN customers rc ON ra.customer_id = rc.customer_id
    WHERE a.account_number = p_acc_no
      AND DATE(t.created_at) BETWEEN p_from AND p_to
    ORDER BY t.created_at;
END$$

CREATE PROCEDURE sp_credit_monthly_interest()
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_acc_id INT;
    DECLARE v_balance DECIMAL(15,2);
    DECLARE v_rate DECIMAL(5,2);
    DECLARE v_interest DECIMAL(15,2);

    DECLARE cur CURSOR FOR
        SELECT account_id, balance, interest_rate
        FROM accounts
        WHERE account_type = 'savings' AND status = 'active';

    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    OPEN cur;

    read_loop: LOOP
        FETCH cur INTO v_acc_id, v_balance, v_rate;
        IF done THEN
            LEAVE read_loop;
        END IF;

        SET v_interest = ROUND(v_balance * (v_rate / 100) / 12, 2);

        UPDATE accounts
        SET balance = balance + v_interest
        WHERE account_id = v_acc_id;

        INSERT INTO transactions
            (transaction_ref, account_id, transaction_type, amount, balance_after, description, created_at)
        VALUES
            (CONCAT('TXN', DATE_FORMAT(NOW(), '%Y%m%d%H%i%s'), LPAD(FLOOR(RAND()*10000),4,'0')),
             v_acc_id, 'interest', v_interest, v_balance + v_interest, 'Monthly Interest Credit', NOW());
    END LOOP;

    CLOSE cur;
END$$

DELIMITER ;

-- ====================================================
-- TRIGGER: MINIMUM BALANCE CHECK
-- Prevent savings account balance from going below Rs.500.
-- Fixed to block only balance-changing updates.
-- ====================================================
DELIMITER $$

CREATE TRIGGER trg_min_balance_check
BEFORE UPDATE ON accounts
FOR EACH ROW
BEGIN
    IF NEW.account_type = 'savings'
       AND NEW.status = 'active'
       AND NEW.balance < 500.00
       AND NEW.balance <> OLD.balance
    THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Balance cannot go below minimum balance of Rs.500';
    END IF;
END$$

DELIMITER ;

-- ====================================================
-- IMPORTANT:
-- 1. Keep customer email UNIQUE. This is correct.
-- 2. Same email creates Savings + Current by adding accounts under same customer_id.
-- 3. Do NOT create duplicate customer rows for same email.
-- 4. Backend should add extra account through accounts table.
-- 5. Deposit and withdrawal are direct transactions, no staff request tables.
-- 6. Fixed Deposit requires manager approval and shows applied/approved/maturity dates.
-- ====================================================
