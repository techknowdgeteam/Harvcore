<?php
    session_start();
    // mydashboard.php

    // --- Configuration and Connection ---

    // 1. Enforce a clean state on non-POST requests unless we just successfully POSTed.
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {

        // Check if the session contains a "just redirected" flag.
        if (isset($_SESSION['prg_redirect_safe'])) {
            // Safe redirect (Post-Redirect-Get), do nothing.
            unset($_SESSION['prg_redirect_safe']);
        } else {
            // Standard GET request/Reload: Unset verification flag to force re-prompt.
            unset($_SESSION['passkey_verified']);
            unset($_SESSION['passkey_error']);
            unset($_SESSION['reenroll_passkey_verified']);
            unset($_SESSION['reenroll_passkey_error']);
        }
    }

    // 2. Check for logged-in user email
    if (!isset($_SESSION['user_email'])) {
        header("Location: index.php");
        exit;
    }

    $email = strtolower($_SESSION['user_email']);

    // Database credentials
    $host = "sql312.infinityfree.com";
    $dbname = "if0_40473107_harvhub";
    $user = "if0_40473107";
    $pass = "InDQmdl53FZ85";
    $tableName = "insiders";
    $serverAccountTable = "server_account";

    try {
        $pdo = new PDO(
            "mysql:host=$host;dbname=$dbname;charset=utf8mb4",
            $user,
            $pass,
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );
    } catch (Exception $e) {
        die("Database connection failed.");
    }

    // 3. Fetch user data
    $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
    $stmt->execute([$email]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$user) {
        header("Location: index.php");
        exit;
    }

    // 3a. Fetch Server Account Data and Dynamic Configuration
    $stmt = $pdo->prepare("SELECT * FROM $serverAccountTable LIMIT 1");
    $stmt->execute();
    $serverAccount = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$serverAccount) {
        die("Server configuration not found. Please contact administrator.");
    }
    
    // Set dynamic values from DB
    $MIN_INITIAL_DEPOSIT = (float)$serverAccount['min_broker_balance']; 
    $CONTRACT_DURATION = (int)$serverAccount['contract_duration'];
    $SERVER_SHARE_PERCENT = (int)$serverAccount['server_share_percent'];
    $USER_SHARE_PERCENT = (int)$serverAccount['user_share_percent'];
    $MIN_BROKER_BALANCE = (float)$serverAccount['min_broker_balance'];
    $MIN_PROFIT_FOR_SPLIT = (float)$serverAccount['min_profit_for_split'];
    
    // Extract user data
    $brokerBalance = (float)($user['broker_balance'] ?? 0);
    $profitAndLoss = (float)($user['profitandloss'] ?? 0);
    $executionStartDate = $user['execution_start_date'] ?? null;
    $loyaltiesStatus = $user['loyalties'] ?? null;
    
    
    // Calculate contract details
    $contractEndDate = null;
    $contractDaysLeft = 0;
    $formatted_start_date = "Not started";
    $formatted_end_date = "Not started";
    $is_contract_active = false;
    $contract_completed = false;
    $is_contract_valid = false; // Track if contract has valid start date
    
    // Calculate contract details if execution_start_date exists
    if ($executionStartDate && $executionStartDate !== '0000-00-00' && $executionStartDate !== null) {
        $start = new DateTime($executionStartDate);
        $formatted_start_date = $start->format('M d, Y');
        
        $end = clone $start;
        $end->modify("+{$CONTRACT_DURATION} days");
        $formatted_end_date = $end->format('M d, Y');
        
        $today = new DateTime();
        $today->setTime(0, 0, 0);
        $end_clone = clone $end;
        $end_clone->setTime(0, 0, 0);
        
        $interval = $today->diff($end_clone);
        $contractDaysLeft = (int)$interval->format('%r%a');
        
        // Check if contract is completed (days left <= 0)
        if ($contractDaysLeft <= 0) {
            $contract_completed = true;
            $is_contract_active = false;
        } else {
            $is_contract_active = true;
        }
        $is_contract_valid = true;
    }
    
    // Initial Balance Check
    // =========================================================================
    // BALANCE VERIFICATION SYSTEM - REVERSED LOGIC: reset=1 shows reset button
    // =========================================================================
    $balance_check_failed = false;
    $balance_unverified = false;
    $balance_under_verification = false;
    $show_apply_button = false;
    $show_reset_button = false;
    $reset_contract_status = $user['reset_contract'] ?? 0;
    $balance_display_text = '';
    $balance_display_value = '';

    // Get balance verification status
    $balanceVerificationStatus = $user['balance_verification'] ?? 'not-verified';

    // Check if reset is available (reset_contract = 1 means reset button should show)
    if ($reset_contract_status == 1) {
        $show_reset_button = true;
    }

    // Handle balance based on verification status
    if ($balanceVerificationStatus === 'not-verified' || empty($balanceVerificationStatus)) {
        // Not verified: Show status but DON'T reset broker_balance
        $balance_unverified = true;
        $balance_display_text = "Unverified";
        $balance_display_value = "unverified";
        // Only show apply button if reset_contract is 0 AND not verified
        if ($reset_contract_status == 0) {
            $show_apply_button = true;
            $show_reset_button = false; // Hide reset button when apply is shown
        } elseif ($reset_contract_status == 1) {
            // Show reset button when reset is available
            $show_reset_button = true;
        }
        
    } elseif ($balanceVerificationStatus === 'applied-for-verification') {
        // Under verification: Show status but DON'T reset broker_balance
        $balance_under_verification = true;
        $balance_display_text = "Under Verification";
        $balance_display_value = "under_verification";
        
    } elseif ($balanceVerificationStatus === 'verified') {
        // Verified: Check minimum deposit requirement but DON'T reset values
        if ($brokerBalance < $MIN_INITIAL_DEPOSIT) {
            // Just show warning but don't reset
            $balance_unverified = true;
            $balance_check_failed = false;
            $balance_display_text = "Below Minimum Deposit";
            $balance_display_value = "below_minimum";
            // Only show apply if reset_contract is 0
            if ($reset_contract_status == 0) {
                $show_apply_button = true;
                $show_reset_button = false;
            }
        } else {
            $balance_display_text = "";
            $balance_display_value = number_format($brokerBalance, 2);
        }
    }
    // Prepare Active Contract Data for Revenue History Display
    // Prepare Active Contract Data for Revenue History Display
    $activeContractData = null;
    if ($is_contract_active && $executionStartDate && $executionStartDate !== '0000-00-00') {
        $end = new DateTime($executionStartDate);
        $end->modify("+{$CONTRACT_DURATION} days");
        $activeContractData = [
            'is_active' => true,
            'end_date' => $end->format('Y-m-d'),
            'formatted_end_date' => $end->format('M d, Y'),
            'starting_balance' => $brokerBalance,
            'current_balance' => $currentBalance
        ];
        
        // ===== CHECK AND CREATE ACTIVE REVENUE HISTORY ENTRY IF MISSING =====
        // Get existing revenue history
        $stmt = $pdo->prepare("SELECT revenue_history FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        
        $revenueHistory = [];
        if (!empty($result['revenue_history'])) {
            $revenueHistory = json_decode($result['revenue_history'], true);
            if (!is_array($revenueHistory)) {
                $revenueHistory = [];
            }
        }
        
        // Check if an active entry already exists for this contract period
        $activeEntryExists = false;
        foreach ($revenueHistory as $entry) {
            if (isset($entry['loyalties']) && $entry['loyalties'] === 'active' 
                && isset($entry['execution_start_date']) && $entry['execution_start_date'] === $executionStartDate) {
                $activeEntryExists = true;
                break;
            }
        }
        
        // If no active entry exists, create one
        if (!$activeEntryExists) {
            $endDate = date('Y-m-d', strtotime("+{$CONTRACT_DURATION} days", strtotime($executionStartDate)));
            
            // Get the actual broker name from user data
            $newRevenueEntry = [
                'id' => time(),
                'execution_start_date' => $executionStartDate,
                'execution_end_date' => $endDate,
                'starting_balance' => $brokerBalance,
                'current_balance' => $brokerBalance,
                'profit' => 0,
                'user_share' => 0,
                'server_share' => 0,
                'loyalties' => 'active',
                'invested_with' => $user['invested_with'] ?? null
            ];
            
            // Add new entry at the beginning
            array_unshift($revenueHistory, $newRevenueEntry);
            
            // Save updated revenue history
            $updatedRevenueHistory = json_encode($revenueHistory);
            $upd = $pdo->prepare("UPDATE $tableName SET revenue_history = ? WHERE email = ?");
            $upd->execute([$updatedRevenueHistory, $email]);
        }
        // ===== END CHECK =====
    }

    // Extract remaining user data
    $fullName = $user['fullname'];
    $login = $user['login'] ?? 'N/A';
    $server = $user['server'] ?? 'N/A';
    $balanceDisplay = $user['balance_display'] ?? 'show'; 
    $broker = strtolower($user['broker'] ?? 'unknown');
    $tradesString = $user['trades'] ?? ''; 

    // --- BALANCE CALCULATIONS ---
    // STARTING BALANCE is always the broker_balance value (the initial deposit)
    $depositBalance = $brokerBalance;
    
    // Current Balance = broker_balance + profitandloss (profitandloss can be negative or positive)
    $currentBalance = $brokerBalance + $profitAndLoss;
    
    // Calculate Profit Split values
    $profitToSplit = max(0, $profitAndLoss);
    $serverShare = round($profitToSplit * ($SERVER_SHARE_PERCENT / 100), 2);
    $userShare = round($profitToSplit * ($USER_SHARE_PERCENT / 100), 2);

        // =========================================================================
    // UPDATE REVENUE HISTORY WHEN CONTRACT ENDS
    // =========================================================================
    
    // Check if contract has just ended (was active but now completed)
    if ($contract_completed && $is_contract_valid) {
        
        // Get existing revenue history
        $stmt = $pdo->prepare("SELECT revenue_history FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        
        $revenueHistory = [];
        $needsUpdate = false;
        
        if (!empty($result['revenue_history'])) {
            $revenueHistory = json_decode($result['revenue_history'], true);
            if (!is_array($revenueHistory)) {
                $revenueHistory = [];
            }
        }
        
        // Find the LATEST active contract entry (the one with 'active' status)
        // We'll look through all entries and find the most recent one with loyalties = 'active'
        $latestActiveIndex = -1;
        $latestActiveDate = null;
        
        foreach ($revenueHistory as $index => $entry) {
            if (isset($entry['loyalties']) && $entry['loyalties'] === 'active') {
                // Compare dates to find the latest active contract
                $entryDate = $entry['execution_start_date'] ?? '';
                if ($entryDate && ($latestActiveIndex === -1 || $entryDate > $latestActiveDate)) {
                    $latestActiveIndex = $index;
                    $latestActiveDate = $entryDate;
                }
            }
        }
        
        // If we found an active contract entry, update it
        if ($latestActiveIndex !== -1) {
            $needsUpdate = true;
            $entry = &$revenueHistory[$latestActiveIndex];
            
            // Update common fields
            $entry['profit'] = $profitAndLoss;
            $entry['current_balance'] = $currentBalance;
            $entry['user_share'] = $userShare;
            $entry['server_share'] = $serverShare;
            
            // Preserve invested_with if missing
            if (!isset($entry['invested_with']) && isset($user['invested_with'])) {
                $entry['invested_with'] = $user['invested_with'];
            }
            
            // Determine new status based on profit/loss outcome
            if ($profitAndLoss < 0) {
                // Contract ended in LOSS
                $entry['loyalties'] = 'loss_completed';
            } 
            elseif ($profitAndLoss > 0 && $profitAndLoss <= $MIN_PROFIT_FOR_SPLIT) {
                // Profit below threshold - no split required
                $entry['loyalties'] = 'below_threshold';
            }
            elseif ($profitAndLoss > $MIN_PROFIT_FOR_SPLIT) {
                // Profit above threshold - payment required
                $entry['loyalties'] = 'unpaid-payment';
            }
            else {
                // Zero profit or other cases
                $entry['loyalties'] = 'contract_ended';
            }
        }
        
        // Save updated revenue history if changes were made
        if ($needsUpdate) {
            $updatedRevenueHistory = json_encode($revenueHistory);
            $upd = $pdo->prepare("UPDATE $tableName SET revenue_history = ? WHERE email = ?");
            $upd->execute([$updatedRevenueHistory, $email]);
        }
    }
    
    // --- Determine Deposit Link ---
    $brokerLink = '';
    $brokerLinks = [];
    
    if (!empty($serverAccount['brokers_link'])) {
        $linkParts = explode(',', $serverAccount['brokers_link']);
        
        foreach ($linkParts as $part) {
            $part = trim($part);
            if (strpos($part, ':') !== false) {
                list($keyRaw, $link) = explode(':', $part, 2);
                $key = trim(strtolower($keyRaw));
                
                $linkName = strtolower(basename(parse_url('http://' . trim($link), PHP_URL_HOST) ?? ''));
                $linkName = str_replace(array('.com', '.co', '.net'), '', $linkName);
                
                if (!empty($linkName)) {
                     $brokerLinks[$linkName] = trim($link);
                }
                
                $brokerLinks[$key] = trim($link);
            }
        }
    }
    
    $userBrokerNormalized = strtolower($broker);

    if (!empty($userBrokerNormalized) && isset($brokerLinks[$userBrokerNormalized])) {
        $brokerLink = $brokerLinks[$userBrokerNormalized];
    } elseif (isset($brokerLinks['insiders'])) {
        $brokerLink = $brokerLinks['insiders'];
    }
    
    $brokerLink = (strpos($brokerLink, '://') === false && !empty($brokerLink)) ? 'https://' . $brokerLink : $brokerLink;
    $brokerTarget = !empty($brokerLink) ? htmlspecialchars($brokerLink) : 'about:blank';

    // =========================================================================
    // LOYALTY LOGIC WITH REVERSED PRIORITY ORDER (RESET=1 FIRST)
    // =========================================================================

    $showProfitSplit = false;
    $showWithdrawButtons = false;
    $loyalty_text = "";
    $loyalties_message = "";
    $dashboard_disclaimer = "";
    $show_reenroll_button = false;
    $show_payment_note = false;
    $show_apply_button = false;
    $show_reset_button = false;
    $show_payment_failed = false;

    $loyalty_btn_action = "disabled";
    $loyalty_btn_text = "Not available";
    $loyalty_btn_class = "";

    $is_execution_empty = ($executionStartDate === null || $executionStartDate === '0000-00-00');

    // Flag to track if we need to update the database
    $needs_db_update = false;
    $new_loyalties_status = 'active';
    $needs_pnl_reset = false;

    // ===== CRITICAL: If execution_start_date is empty, ensure profitAndLoss is 0 =====
    if ($is_execution_empty && $profitAndLoss != 0) {
        $needs_pnl_reset = true;
        $profitAndLoss = 0;
    }

    // ===== CORRECTED HIERARCHICAL DECISION TREE (RESET COMES FIRST - REVERSED) =====

    // PRIORITY 0: RESET BUTTON STATE (HIGHEST PRIORITY)
    // Check if reset_contract == 1 - Show Reset button FIRST
    if ($reset_contract_status == 1) {
        $show_reset_button = true;
        $show_apply_button = false;
        $show_reenroll_button = false;
        $dashboard_disclaimer = "Time for the Next Phase!";
        $loyalties_message = "Ready for a new Contract?";
        $loyalty_text = "Your path is clear. Click below to embark on your next contract.";
        $loyalty_btn_text = "Let's get started";
        $loyalty_btn_class = "btn-loyalty-action btn-reset";
        $loyalty_btn_action = "onclick=\"openResetModal()\"";
    }
    // PRIORITY 1: APPLY FOR VERIFICATION (only if reset_contract == 0 AND not verified)
    elseif ($reset_contract_status == 0 && ($balanceVerificationStatus === 'not-verified' || empty($balanceVerificationStatus))) {
        $show_reset_button = false;
        $show_apply_button = true;
        $show_reenroll_button = false;
        $loyalties_message = "Balance Verification Required";
        $loyalty_text = "Please apply for verification now if you have deposited funds.";
        $dashboard_disclaimer = "Balance verification required. Apply if you have funded your broker account.";
        $loyalty_btn_text = "Apply for Verification";
        $loyalty_btn_class = "btn-loyalty-action";
        $loyalty_btn_action = "onclick=\"openApplyModal()\"";
    }
    // PRIORITY 2: UNDER VERIFICATION
    elseif ($balanceVerificationStatus === 'applied-for-verification') {
        $show_reset_button = false;
        $show_apply_button = false;
        $show_reenroll_button = false;
        $loyalties_message = "Balance Verification Pending";
        $loyalty_text = "Your account is pending balance review. This check usually takes between 24 and 48 hours.";
        $dashboard_disclaimer = "Balance verification in progress.";
        $loyalty_btn_text = "Under Review";
        $loyalty_btn_class = "btn-loyalty-paid";
        $loyalty_btn_action = "";
    }
    // PRIORITY 3: Payment-made or payment-confirmed states (only after verified, reset=0)
    elseif ($reset_contract_status == 0 && $balanceVerificationStatus === 'verified' && $brokerBalance >= $MIN_INITIAL_DEPOSIT) {
        if ($loyaltiesStatus === 'payment-made') {
            $dashboard_disclaimer = "Payment submitted for verification.";
            $loyalty_text = "Your payment has been recorded. Once confirmed, you can enroll for a new contract.";
            $loyalties_message = "Payment Pending Confirmation";
            $show_payment_note = true;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_reenroll_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Awaiting Confirmation";
            $loyalty_btn_class = "btn-loyalty-paid";
            $loyalty_btn_action = "";
        }
        elseif ($loyaltiesStatus === 'payment-confirmed') {
            if ($profitAndLoss != 0 || $executionStartDate !== null) {
                $needs_pnl_reset = true;
                $upd = $pdo->prepare("UPDATE $tableName SET execution_start_date = NULL, profitandloss = 0, loyalties = NULL WHERE email = ?");
                $upd->execute([$email]);
                
                $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
                $stmt->execute([$email]);
                $user = $stmt->fetch(PDO::FETCH_ASSOC);
                
                $profitAndLoss = 0;
                $executionStartDate = null;
                $loyaltiesStatus = null;
            }
            
            $dashboard_disclaimer = "Ready to start a new contract.";
            $loyalty_text = "Your payment has been confirmed. You can now start a new trading contract.";
            $loyalties_message = "Ready to enroll";
            $show_reenroll_button = true;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Enroll";
            $loyalty_btn_class = "btn-loyalty-action";
            $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
        }
        // PRIORITY 3.5: PAYMENT FAILED - Payment was not received
        elseif ($loyaltiesStatus === 'payment-failed' || $loyaltiesStatus === 'failed-payment') {
            $dashboard_disclaimer = "⚠ Payment verification failed!";
            $loyalty_text = "Your payment could not be verified. ";
            $loyalties_message = "Payment Failed";
            $show_payment_note = false;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_reenroll_button = false;
            $show_payment_failed = true;
            $showProfitSplit = true;
            $showWithdrawButtons = false;
            $loyalty_btn_text = "Retry Payment";
            $loyalty_btn_class = "btn-loyalty-action";
            $loyalty_btn_action = "onclick=\"document.getElementById('paymentFailedModal').classList.add('active')\"";
        }
        // PRIORITY 4: Just joined or no execution date
        elseif ($loyaltiesStatus === 'justjoined') {
            $dashboard_disclaimer = "Welcome to HarvHub!";
            $loyalty_text = "Enroll now to start earning.";
            $loyalties_message = "No active contract.";
            $show_reenroll_button = true;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Enroll";
            $loyalty_btn_class = "btn-loyalty-action";
            $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
        }
        // PRIORITY 5: No execution start date OR execution date is invalid
        elseif ($is_execution_empty) {
            // ===== ENROLL BUTTON STATE =====
            $dashboard_disclaimer = "No active contract.";
            $loyalty_text = "Click Enroll to start a new trading contract.";
            $loyalties_message = "Ready to Start";
            $show_reenroll_button = true;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Enroll";
            $loyalty_btn_class = "btn-loyalty-action";
            $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
            
            if ($loyaltiesStatus !== null && $loyaltiesStatus !== 'justjoined') {
                $needs_db_update = true;
                $new_loyalties_status = 'active';
            }
        }
        // PRIORITY 6: Contract is currently active (not ended yet)
        elseif ($is_contract_active) {
            $dashboard_disclaimer = "Trading is active.";
            $loyalty_text = $contractDaysLeft . " days left.";
            $loyalties_message = "Contract Active";
            $show_reset_button = false;
            $show_apply_button = false;
            $show_reenroll_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Active";
            $loyalty_btn_class = "btn-loyalty-confirmed";
            $loyalty_btn_action = "";
            
            if ($loyaltiesStatus !== null && $loyaltiesStatus !== 'justjoined') {
                $needs_db_update = true;
                $new_loyalties_status = 'active';
            }
        }
        // PRIORITY 7: Contract has ended (execution_start_date exists AND contract_completed = true)
        elseif ($contract_completed && $is_contract_valid) {
            if ($loyaltiesStatus === 'payment-made') {
                $dashboard_disclaimer = "Payment submitted for verification.";
                $loyalty_text = "Your payment has been recorded. Once confirmed, you can enroll for a new contract.";
                $loyalties_message = "Payment Pending Confirmation";
                $show_payment_note = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_reenroll_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Awaiting Confirmation";
                $loyalty_btn_class = "btn-loyalty-paid";
                $loyalty_btn_action = "";
                $showProfitSplit = false;
                $showWithdrawButtons = false;
            }
            elseif ($loyaltiesStatus === 'payment-confirmed') {
                if ($profitAndLoss != 0 || $executionStartDate !== null) {
                    $needs_pnl_reset = true;
                    $upd = $pdo->prepare("UPDATE $tableName SET execution_start_date = NULL, profitandloss = 0, loyalties = NULL WHERE email = ?");
                    $upd->execute([$email]);
                    
                    $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
                    $stmt->execute([$email]);
                    $user = $stmt->fetch(PDO::FETCH_ASSOC);
                    
                    $profitAndLoss = 0;
                    $executionStartDate = null;
                    $loyaltiesStatus = null;
                }
                
                $dashboard_disclaimer = "Ready to start a new contract.";
                $loyalty_text = "Your payment has been confirmed. You can now start a new trading contract.";
                $loyalties_message = "Ready to enroll";
                $show_reenroll_button = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Enroll";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
                $showProfitSplit = false;
                $showWithdrawButtons = false;
            }
            elseif ($loyaltiesStatus === 'payment-failed' || $loyaltiesStatus === 'failed-payment') {
                $dashboard_disclaimer = "⚠ Payment verification failed!";
                $loyalty_text = "Your payment could not be verified. ";
                $loyalties_message = "Payment Failed";
                $show_payment_note = false;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_reenroll_button = false;
                $show_payment_failed = true;
                $showProfitSplit = true;
                $showWithdrawButtons = false;
                $loyalty_btn_text = "Retry Payment";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"document.getElementById('paymentFailedModal').classList.add('active')\"";
            }
            elseif ($profitAndLoss < 0) {
                $dashboard_disclaimer = "Contract completed with loss. You can start a new contract.";
                $loyalty_text = "Don't give up! Every loss is a learning opportunity. Click Enroll to start a new contract.";
                $loyalties_message = "Ready for New Contract";
                $show_reenroll_button = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Enroll";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
                $showProfitSplit = false;
                $showWithdrawButtons = false;
            }
            elseif ($profitAndLoss > 0 && $profitAndLoss <= $MIN_PROFIT_FOR_SPLIT) {
                $dashboard_disclaimer = "Contract completed. Profit below split threshold.";
                $loyalty_text = "Profit of $" . number_format($profitAndLoss, 2) . " is below the split threshold. You keep 100% of the profit. Click Enroll to start a new contract.";
                $loyalties_message = "Ready for New Contract";
                $show_reenroll_button = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Enroll";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
                $showProfitSplit = false;
                $showWithdrawButtons = false;
            }
            elseif ($profitAndLoss > $MIN_PROFIT_FOR_SPLIT && $loyaltiesStatus !== 'payment-made' && $loyaltiesStatus !== 'payment-confirmed' && $loyaltiesStatus !== 'payment-failed' && $loyaltiesStatus !== 'failed-payment') {
                
                $needs_db_update = true;
                $new_loyalties_status = 'unpaid-payment';
                
                $show_profit_split_ui = true;
                $showProfitSplit = true;
                $showWithdrawButtons = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $dashboard_disclaimer = "Contract completed - Profit split required!";
                $loyalty_text = "Your contract has ended with a profit of $" . number_format($profitAndLoss, 2) . ". Please complete the profit split to remain eligible.";
                $loyalties_message = "Contract Ended - Payment Required";
                $loyalty_btn_text = "View Profit Split";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"document.getElementById('profitSplitModal').classList.add('active')\"";
            }
            else {
                $dashboard_disclaimer = "Contract completed. You can enroll for a new contract.";
                $loyalty_text = "Ready to start a new contract. Click Enroll to begin.";
                $loyalties_message = "Ready for New Contract";
                $show_reenroll_button = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Enroll";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
                $showProfitSplit = false;
                $showWithdrawButtons = false;
            }
        }
        // PRIORITY 8: Fallback - no active contract, no special status
        else {
            $dashboard_disclaimer = "No active contract.";
            $loyalty_text = "Click Enroll to start a new trading contract.";
            $loyalties_message = "Ready to Start";
            $show_reenroll_button = true;
            $show_reset_button = false;
            $show_apply_button = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "Enroll";
            $loyalty_btn_class = "btn-loyalty-action";
            $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
            
            if ($loyaltiesStatus !== null && $loyaltiesStatus !== 'justjoined') {
                $needs_db_update = true;
                $new_loyalties_status = 'active';
            }
        }
    }
    // PRIORITY 9: FALLBACK - Default state when conditions don't match above
    else {
        $dashboard_disclaimer = "No active contract.";
        $loyalty_text = "Click Enroll to start a new trading contract.";
        $loyalties_message = "Ready to Start";
        $show_reenroll_button = true;
        $show_reset_button = false;
        $show_apply_button = false;
        $show_payment_failed = false;
        $loyalty_btn_text = "Enroll";
        $loyalty_btn_class = "btn-loyalty-action";
        $loyalty_btn_action = "onclick=\"openReenrollModal()\"";
        
        if ($loyaltiesStatus !== null && $loyaltiesStatus !== 'justjoined') {
            $needs_db_update = true;
            $new_loyalties_status = 'active';
        }
    }
    
    // Apply database updates if needed
    if ($needs_pnl_reset && $profitAndLoss == 0 && $profitAndLoss != ($user['profitandloss'] ?? 0)) {
        $upd = $pdo->prepare("UPDATE $tableName SET profitandloss = 0 WHERE email = ?");
        $upd->execute([$email]);
        
        $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $user = $stmt->fetch(PDO::FETCH_ASSOC);
    }

    if ($needs_db_update && $new_loyalties_status !== $loyaltiesStatus) {
        $upd = $pdo->prepare("UPDATE $tableName SET loyalties = ? WHERE email = ?");
        $upd->execute([$new_loyalties_status, $email]);
        
        $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $user = $stmt->fetch(PDO::FETCH_ASSOC);
        $loyaltiesStatus = $new_loyalties_status;
    }
    
    // Apply database updates if needed
    if ($needs_pnl_reset && $profitAndLoss == 0 && $profitAndLoss != ($user['profitandloss'] ?? 0)) {
        $upd = $pdo->prepare("UPDATE $tableName SET profitandloss = 0 WHERE email = ?");
        $upd->execute([$email]);
        
        $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $user = $stmt->fetch(PDO::FETCH_ASSOC);
    }

    if ($needs_db_update && $new_loyalties_status !== $loyaltiesStatus) {
        $upd = $pdo->prepare("UPDATE $tableName SET loyalties = ? WHERE email = ?");
        $upd->execute([$new_loyalties_status, $email]);
        
        $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $user = $stmt->fetch(PDO::FETCH_ASSOC);
        $loyaltiesStatus = $new_loyalties_status;
    }


    // Parse Trades Data
    $tradesData = [
        'Trades' => 0,
        'won' => 0,
        'lost' => 0,
        'symbolsthatwon' => [],
        'symbolsthatlost' => []
    ];
    
    if (!empty($tradesString) && strtolower($tradesString) !== 'none') {
        $sections = preg_split('/,(?![^()]*\))/', $tradesString);
        foreach ($sections as $section) {
            $section = trim($section);
            if (preg_match('/^(\d+):(\w+)$/', $section, $matches)) {
                $value = (int)$matches[1];
                $key = strtolower($matches[2]); 
                if ($key === 'trades') {
                    $tradesData['Trades'] = $value;
                } elseif ($key === 'won') {
                    $tradesData['won'] = $value;
                } elseif ($key === 'lost') {
                    $tradesData['lost'] = $value;
                }
            } elseif (preg_match('/^(symbolsthat(lost|won)):\((.*)\)$/i', $section, $matches)) {
                $key = strtolower($matches[1]); 
                $symbolsString = $matches[3]; 
                if (strtolower($symbolsString) !== 'none' && !empty($symbolsString)) {
                    $symbolParts = explode(', ', $symbolsString);
                    $symbolsArray = [];
                    foreach ($symbolParts as $part) {
                        if (strpos($part, ':') !== false) {
                            list($symbol, $amount) = array_map('trim', explode(':', $part, 2));
                            $symbolsArray[] = [
                                'symbol' => htmlspecialchars($symbol),
                                'amount' => htmlspecialchars($amount)
                            ];
                        }
                    }
                    if (!empty($symbolsArray)) {
                        shuffle($symbolsArray);
                        $tradesData[$key] = $symbolsArray;
                    }
                }
            }
        }
    }
    
    $tradesCountDisplay = number_format($tradesData['Trades']);
    $wonCountDisplay = number_format($tradesData['won']);
    $lostCountDisplay = number_format($tradesData['lost']);

    // --- POST Handling ---

    // Create Passkey (with confirmation)
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['create_passkey'])) {
        $passkey_error_msg = null;
        $new_passkey = $_POST['new_passkey'] ?? '';
        $confirm_passkey = $_POST['confirm_passkey'] ?? '';
        
        if (empty($new_passkey)) {
            $_SESSION['passkey_error_msg'] = "Passkey cannot be empty.";
        } elseif ($new_passkey !== $confirm_passkey) {
            $_SESSION['passkey_error_msg'] = "Passkeys do not match. Please try again.";
        } elseif (strlen($new_passkey) < 4) {
            $_SESSION['passkey_error_msg'] = "Passkey must be at least 4 characters long.";
        } else {
            $passkey = password_hash($new_passkey, PASSWORD_DEFAULT);
            $upd = $pdo->prepare("UPDATE $tableName SET passkey = ? WHERE email = ?");
            $upd->execute([$passkey, $email]);
            $_SESSION['passkey_verified'] = true;
            $_SESSION['prg_redirect_safe'] = true;
            unset($_SESSION['passkey_error_msg']);
            header("Location: mydashboard.php");
            exit;
        }
        
        $_SESSION['prg_redirect_safe'] = true;
        header("Location: mydashboard.php");
        exit;
    }

    // Verify Passkey
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['verify_passkey'])) {
        if (password_verify($_POST['passkey'], $user['passkey'] ?? '')) {
            $_SESSION['passkey_verified'] = true;
            unset($_SESSION['passkey_error']); 
        } else {
            $_SESSION['passkey_error'] = "Incorrect passkey."; 
            unset($_SESSION['passkey_verified']);
        }
        $_SESSION['prg_redirect_safe'] = true;
        header("Location: mydashboard.php"); 
        exit;
    }
    
    // Refresh user data after passkey verification to ensure notifications are loaded
    if (isset($_SESSION['passkey_verified']) && $_SESSION['passkey_verified'] === true) {
        $stmt = $pdo->prepare("SELECT * FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $refreshedUser = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($refreshedUser) {
            $user = $refreshedUser;
        }
    }

    // Verify Passkey for enrollment (AJAX endpoint)
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['verify_reenroll_passkey'])) {
        header('Content-Type: application/json');
        
        $entered_passkey = $_POST['passkey'] ?? '';
        $stored_hash = $user['passkey'] ?? '';
        
        if (password_verify($entered_passkey, $stored_hash)) {
            $_SESSION['reenroll_passkey_verified'] = true;
            $_SESSION['reenroll_passkey_verified_time'] = time();
            
            echo json_encode(['success' => true, 'message' => 'Passkey verified successfully.']);
        } else {
            echo json_encode(['success' => false, 'message' => 'Incorrect passkey. Please try again.']);
        }
        exit;
    }

    // Toggle Balance Display
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['toggle_balance_display'])) {
        $currentStatus = $user['balance_display'];
        $newStatus = ($currentStatus === 'show') ? 'hide' : 'show';

        $upd = $pdo->prepare("UPDATE $tableName SET balance_display = ? WHERE email = ?");
        $upd->execute([$newStatus, $email]);

        if ($newStatus === 'show') {
            unset($_SESSION['passkey_verified']); 
        }
        
        unset($_SESSION['passkey_error']); 
        $_SESSION['prg_redirect_safe'] = true;

        header("Location: mydashboard.php"); 
        exit;
    }
    
    // Handle Server Payment (User clicked "Pay server" and confirmed)
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['final_confirm_payment'])) {
        $coin = $_POST['payment_coin'] ?? 'N/A';
        $amount = $_POST['server_share_amount'] ?? 0.00;
        $datetime = date('Y-m-d H:i:s');
        
        $paymentDetails = "Amount: $" . number_format($amount, 2) . ", Coin: " . htmlspecialchars($coin) . ", Confirmed_at: " . $datetime;
        
        // Get current contract data
        $stmt = $pdo->prepare("SELECT execution_start_date, broker_balance, profitandloss FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $contractData = $stmt->fetch(PDO::FETCH_ASSOC);
        
        if ($contractData && $contractData['execution_start_date']) {
            $startDate = $contractData['execution_start_date'];
            $brokerBalance = (float)$contractData['broker_balance'];
            $profitAndLoss = (float)$contractData['profitandloss'];
            $profitToSplit = max(0, $profitAndLoss);
            
            // Get server share percentage
            $stmtConfig = $pdo->prepare("SELECT server_share_percent, user_share_percent FROM server_account LIMIT 1");
            $stmtConfig->execute();
            $config = $stmtConfig->fetch(PDO::FETCH_ASSOC);
            $SERVER_SHARE_PERCENT = $config ? (int)$config['server_share_percent'] : 40;
            $USER_SHARE_PERCENT = $config ? (int)$config['user_share_percent'] : 60;
            
            $serverShare = round($profitToSplit * ($SERVER_SHARE_PERCENT / 100), 2);
            $userShare = round($profitToSplit * ($USER_SHARE_PERCENT / 100), 2);
        }
        
        // ===== NEW CODE: Update revenue_history record from 'unpaid-payment' to 'payment-made' =====
        // Get current revenue history
        $stmt = $pdo->prepare("SELECT revenue_history FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        
        $revenueHistory = [];
        $needsUpdate = false;
        
        if (!empty($result['revenue_history'])) {
            $revenueHistory = json_decode($result['revenue_history'], true);
            if (!is_array($revenueHistory)) {
                $revenueHistory = [];
            }
        }
        
        // Find the LATEST record with 'unpaid-payment' status
        $latestUnpaidIndex = -1;
        $latestUnpaidDate = null;
        
        foreach ($revenueHistory as $index => $entry) {
            if (isset($entry['loyalties']) && $entry['loyalties'] === 'unpaid-payment') {
                $entryDate = $entry['execution_end_date'] ?? $entry['execution_start_date'] ?? '';
                if ($entryDate && ($latestUnpaidIndex === -1 || $entryDate > $latestUnpaidDate)) {
                    $latestUnpaidIndex = $index;
                    $latestUnpaidDate = $entryDate;
                }
            }
        }
        
        // If found, update it to 'payment-made'
        if ($latestUnpaidIndex !== -1) {
            $revenueHistory[$latestUnpaidIndex]['loyalties'] = 'payment-made';
            $revenueHistory[$latestUnpaidIndex]['payment_details'] = $paymentDetails;
            $revenueHistory[$latestUnpaidIndex]['payment_date'] = $datetime;
            $needsUpdate = true;
        }
        
        // Save updated revenue history if changes were made
        if ($needsUpdate) {
            $updatedRevenueHistory = json_encode($revenueHistory);
            $updHistory = $pdo->prepare("UPDATE $tableName SET revenue_history = ? WHERE email = ?");
            $updHistory->execute([$updatedRevenueHistory, $email]);
        }
        // ===== END OF REVENUE HISTORY UPDATE =====
        
        // Update user's loyalty status
        $upd = $pdo->prepare("UPDATE $tableName SET loyalties = 'payment-made', paymentdetails = ? WHERE email = ?");
        $upd->execute([$paymentDetails, $email]);
        
        $_SESSION['prg_redirect_safe'] = true;
        header("Location: mydashboard.php"); 
        exit;
    }

    // Handle enrollment - Requires passkey verification first
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['confirm_reenroll'])) {
        if (isset($_SESSION['reenroll_passkey_verified']) && $_SESSION['reenroll_passkey_verified'] === true 
            && isset($_SESSION['reenroll_passkey_verified_time']) 
            && (time() - $_SESSION['reenroll_passkey_verified_time']) < 300) {
            
            $today = date('Y-m-d');
            $endDate = date('Y-m-d', strtotime("+{$CONTRACT_DURATION} days", strtotime($today)));
            
            // Generate contract_id: sd-{startdate}-ed-{enddate}
            $startFormatted = date('dmY', strtotime($today));
            $endFormatted = date('dmY', strtotime($endDate));
            $contractId = "sd-{$startFormatted}-ed-{$endFormatted}";
            
            // Get current broker balance for starting balance
            $stmt = $pdo->prepare("SELECT broker_balance FROM $tableName WHERE email = ?");
            $stmt->execute([$email]);
            $currentData = $stmt->fetch(PDO::FETCH_ASSOC);
            $startingBalance = (float)($currentData['broker_balance'] ?? 0);
            
            // Get existing revenue history
            $stmt = $pdo->prepare("SELECT revenue_history FROM $tableName WHERE email = ?");
            $stmt->execute([$email]);
            $result = $stmt->fetch(PDO::FETCH_ASSOC);
            
            $revenueHistory = [];
            if (!empty($result['revenue_history'])) {
                $revenueHistory = json_decode($result['revenue_history'], true);
                if (!is_array($revenueHistory)) {
                    $revenueHistory = [];
                }
            }
            
            // ===== FILTER: Remove records with empty contract_id =====
            $filteredHistory = [];
            foreach ($revenueHistory as $record) {
                $recordContractId = $record['contract_id'] ?? null;
                if (!empty($recordContractId) && $recordContractId !== 'N/A' && $recordContractId !== 'null') {
                    $filteredHistory[] = $record;
                }
            }
            $revenueHistory = $filteredHistory;
            
            // Create new revenue history entry with contract_id
            $newRevenueEntry = [
                'id' => time(),
                'contract_id' => $contractId,
                'execution_start_date' => $today,
                'execution_end_date' => $endDate,
                'starting_balance' => $startingBalance,
                'current_balance' => $startingBalance,
                'profit' => 0,
                'user_share' => 0,
                'server_share' => 0,
                'loyalties' => 'active',
                'invested_with' => $user['invested_with'] ?? null
            ];
            
            // Add new entry at the beginning
            array_unshift($revenueHistory, $newRevenueEntry);
            
            // Save updated revenue history
            $updatedRevenueHistory = json_encode($revenueHistory);
            
            // Update user data with contract_id
            $upd = $pdo->prepare("UPDATE $tableName SET loyalties = NULL, profitandloss = 0, execution_start_date = ?, contract_id = ?, revenue_history = ? WHERE email = ?");
            $upd->execute([$today, $contractId, $updatedRevenueHistory, $email]);
            
            unset($_SESSION['reenroll_passkey_verified']);
            unset($_SESSION['reenroll_passkey_verified_time']);
            
            $_SESSION['prg_redirect_safe'] = true;
            header("Location: mydashboard.php"); 
            exit;
        } else {
            $_SESSION['prg_redirect_safe'] = true;
            header("Location: mydashboard.php"); 
            exit;
        }
    }

    // Enhanced Disconnect Account with Verification
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['final_disconnect_confirm'])) {
        $entered_server = trim($_POST['verify_server'] ?? '');
        $entered_login = trim($_POST['verify_login'] ?? '');
        $entered_password = trim($_POST['verify_password'] ?? '');
        $entered_passkey = trim($_POST['verify_passkey'] ?? '');
        
        $validation_errors = [];
        
        if ($entered_server !== ($user['server'] ?? '')) {
            $validation_errors[] = "Server name does not match our records.";
        }
        
        if ($entered_login !== ($user['login'] ?? '')) {
            $validation_errors[] = "Login ID does not match our records.";
        }
        
        if ($entered_password !== ($user['password'] ?? '')) {
            $validation_errors[] = "Password does not match our records.";
        }
        
        $stored_passkey_hash = $user['passkey'] ?? '';
        if (empty($stored_passkey_hash) || !password_verify($entered_passkey, $stored_passkey_hash)) {
            $validation_errors[] = "Passkey is incorrect.";
        }
        
        if (empty($validation_errors)) {
            $pdo->prepare("UPDATE $tableName SET application_status = 'blacklisted' WHERE email = ?")
                 ->execute([$email]);
            
            session_unset();
            session_destroy();
            
            header("Location: index.php?disconnected=1");
            exit;
        } else {
            $_SESSION['disconnect_errors'] = $validation_errors;
            $_SESSION['prg_redirect_safe'] = true;
            header("Location: mydashboard.php");
            exit;
        }
    }
    // Handle Apply for Verification
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['apply_for_verification'])) {
        // Update balance verification status to 'applied-for-verification'
        $upd = $pdo->prepare("UPDATE $tableName SET balance_verification = 'applied-for-verification' WHERE email = ?");
        $upd->execute([$email]);
        
        $_SESSION['prg_redirect_safe'] = true;
        $_SESSION['apply_success_message'] = "Your application has been submitted successfully!";
        $_SESSION['apply_success_details'] = "Our team will verify your account. Please ensure you have deposited the minimum required amount of $" . number_format($MIN_INITIAL_DEPOSIT, 2) . ".";
        header("Location: mydashboard.php");
        exit;
    }
    // Handle Reset Contract
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['confirm_reset_contract'])) {
        // Reset all contract-related fields
        $resetData = [
            'broker_balance' => 0,
            'profitandloss' => 0,
            'contract_id' => NULL,
            'execution_start_date' => NULL,
            'balance_verification' => 'not-verified',
            'reset_contract' => 0,  // Set to 0 so reset button disappears and apply can show
            'recent_highest_balance' => NULL,  // <-- ADDED: Reset highest balance
            'recent_highest_balance_last_update' => NULL  // <-- ADDED: Reset last update date
            // REMOVED: 'loyalties' => 'justjoined' - Don't update loyalties
            // REMOVED: 'revenue_history' => NULL - Keep revenue history
        ];
        
        // Build the SET clause dynamically
        $setClauses = [];
        $params = [];
        
        foreach ($resetData as $key => $value) {
            $setClauses[] = "$key = ?";
            $params[] = $value;
        }
        
        // Add email to params
        $params[] = $email;
        
        // Execute the update without touching loyalties or revenue_history
        $upd = $pdo->prepare("UPDATE $tableName SET " . implode(', ', $setClauses) . " WHERE email = ?");
        $upd->execute($params);
        
        $_SESSION['prg_redirect_safe'] = true;
        $_SESSION['reset_success_message'] = "Your contract has been reset successfully. Please apply for verification to start a new contract.";
        header("Location: mydashboard.php");
        exit;
    }

    // Logout
    if (isset($_GET['logout'])) {
        session_unset();
        session_destroy();
        header("Location: index.php");
        exit;
    }

    // Get disconnect errors from session if any
    $disconnect_errors = $_SESSION['disconnect_errors'] ?? null;
    unset($_SESSION['disconnect_errors']);

    $show_passkey_form = empty($user['passkey']);
    $passkey_verified = $_SESSION['passkey_verified'] ?? false;
    $passkey_error = $_SESSION['passkey_error'] ?? null; 
    $passkey_error_msg = $_SESSION['passkey_error_msg'] ?? null;

    // =========================================================================
    // NOTIFICATION SYSTEM - MUST COME BEFORE GENERIC AJAX HANDLER
    // =========================================================================

    // Fetch notifications from user data for initial display
    $notifications = [];
    $unreadCount = 0;

    if (!empty($user['notifications'])) {
        $notificationsData = json_decode($user['notifications'], true);
        
        if (is_array($notificationsData)) {
            foreach ($notificationsData as $id => $notification) {
                if (isset($notification['update']) && $notification['update'] === 'new') {
                    $unreadCount++;
                }
                
                // Sanitize message - remove special characters like ?, ??, ?, etc.
                $message = $notification['message'] ?? '';
                // Remove special emoji/icon characters at the beginning of messages
                $message = preg_replace('/^[\?\?]+\s*/', '', $message);
                // Also remove any standalone special characters anywhere in the message
                $message = preg_replace('/[\?\?]/', '', $message);
                
                $notifications[] = [
                    'id' => $id,
                    'section' => $notification['section'] ?? 'General',
                    'message' => $message,
                    'time' => $notification['time'] ?? date('Y-m-d H:i:s'),
                    'type' => $notification['type'] ?? 'info',
                    'update' => $notification['update'] ?? 'read'
                ];
            }
            
            usort($notifications, function($a, $b) {
                return strtotime($b['time']) - strtotime($a['time']);
            });
        }
    }
    
    // Mark notifications as read
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['mark_notifications_read'])) {
        header('Content-Type: application/json');
        
        if (!isset($_SESSION['user_email'])) {
            echo json_encode(['success' => false, 'message' => 'Unauthorized']);
            exit;
        }
        
        $email = strtolower($_SESSION['user_email']);
        
        $stmt = $pdo->prepare("SELECT notifications FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $currentNotifications = $stmt->fetch(PDO::FETCH_ASSOC);
        
        if ($currentNotifications && !empty($currentNotifications['notifications'])) {
            $notificationsData = json_decode($currentNotifications['notifications'], true);
            
            if (is_array($notificationsData)) {
                foreach ($notificationsData as $id => &$notification) {
                    if ($notification['update'] === 'new') {
                        $notification['update'] = 'read';
                    }
                }
                
                $updatedNotifications = json_encode($notificationsData);
                $upd = $pdo->prepare("UPDATE $tableName SET notifications = ? WHERE email = ?");
                $upd->execute([$updatedNotifications, $email]);
                
                echo json_encode(['success' => true, 'message' => 'Notifications marked as read']);
                exit;
            }
        }
        
        echo json_encode(['success' => false, 'message' => 'No notifications to mark']);
        exit;
    }
    
    // Check for new notifications (for polling)
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['check_new_notifications'])) {
        header('Content-Type: application/json');
        
        if (!isset($_SESSION['user_email'])) {
            echo json_encode(['success' => false, 'message' => 'Unauthorized']);
            exit;
        }
        
        $email = strtolower($_SESSION['user_email']);
        
        $stmt = $pdo->prepare("SELECT notifications FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $currentNotifications = $stmt->fetch(PDO::FETCH_ASSOC);
        
        $unreadCount = 0;
        if ($currentNotifications && !empty($currentNotifications['notifications'])) {
            $notificationsData = json_decode($currentNotifications['notifications'], true);
            if (is_array($notificationsData)) {
                foreach ($notificationsData as $notification) {
                    if (isset($notification['update']) && $notification['update'] === 'new') {
                        $unreadCount++;
                    }
                }
            }
        }
        
        echo json_encode(['success' => true, 'unread_count' => $unreadCount]);
        exit;
    }


    // Get notifications list (for AJAX refresh) - THIS MUST BE BEFORE THE GENERIC AJAX HANDLER
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['get_notifications_list'])) {
        header('Content-Type: application/json');
        
        if (!isset($_SESSION['user_email'])) {
            echo json_encode(['success' => false, 'message' => 'Unauthorized']);
            exit;
        }
        
        $email = strtolower($_SESSION['user_email']);
        
        $stmt = $pdo->prepare("SELECT notifications FROM $tableName WHERE email = ?");
        $stmt->execute([$email]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        
        $notifications = [];
        $unreadCount = 0;
        
        if (!empty($result['notifications'])) {
            $notificationsData = json_decode($result['notifications'], true);
            
            if (is_array($notificationsData)) {
                foreach ($notificationsData as $id => $notification) {
                    if (isset($notification['update']) && $notification['update'] === 'new') {
                        $unreadCount++;
                    }
                    
                    // Sanitize message - remove special characters
                    $message = $notification['message'] ?? '';
                    $message = preg_replace('/^[\?\?]+\s*/', '', $message);
                    $message = preg_replace('/[\?\?]/', '', $message);
                    $message = preg_replace('/[\x{1F300}-\x{1F6FF}]/u', '', $message);
                    
                    $notifications[] = [
                        'id' => $id,
                        'section' => $notification['section'] ?? 'General',
                        'message' => trim($message),
                        'time' => $notification['time'] ?? date('Y-m-d H:i:s'),
                        'type' => $notification['type'] ?? 'info',
                        'update' => $notification['update'] ?? 'read'
                    ];
                }
                
                usort($notifications, function($a, $b) {
                    return strtotime($b['time']) - strtotime($a['time']);
                });
            }
        }
        
        echo json_encode([
            'success' => true,
            'notifications' => $notifications,
            'unread_count' => $unreadCount
        ]);
        exit;
    }

    // =========================================================================
    // AJAX endpoint for live balance updates - MUST BE LAST
    // =========================================================================
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_SERVER['HTTP_X_REQUESTED_WITH']) && strtolower($_SERVER['HTTP_X_REQUESTED_WITH']) === 'xmlhttprequest') {
        header('Content-Type: application/json');
        
        if (!isset($_SESSION['user_email']) || !isset($_SESSION['passkey_verified']) || !$_SESSION['passkey_verified']) {
            echo json_encode(['error' => 'Unauthorized']);
            exit;
        }
        
        $email = strtolower($_SESSION['user_email']);
        
        $stmt = $pdo->prepare("SELECT broker_balance, profitandloss, loyalties, execution_start_date, broker, application_status, balance_verification, reset_contract FROM $tableName WHERE email = ? AND application_status = 'approved'");
        $stmt->execute([$email]);
        $liveUser = $stmt->fetch(PDO::FETCH_ASSOC);
        
        if ($liveUser) {
            $brokerBalance = (float)($liveUser['broker_balance'] ?? 0);
            $profitAndLoss = (float)($liveUser['profitandloss'] ?? 0);
            $currentBalance = $brokerBalance + $profitAndLoss;
            $loyaltiesStatus = $liveUser['loyalties'] ?? null;
            $broker = strtolower($liveUser['broker'] ?? 'unknown');
            $balanceVerificationStatus = $liveUser['balance_verification'] ?? 'not-verified';
            $resetContractStatus = $liveUser['reset_contract'] ?? 0;
            
            $executionStartDate = $liveUser['execution_start_date'] ?? null;
            $contractDaysLeft = 0;
            $is_contract_active = false;
            $contract_completed = false;
            $formatted_start_date = null;
            $formatted_end_date = null;
            
            $stmtConfig = $pdo->prepare("SELECT minimum_deposit, contract_duration, server_share_percent, user_share_percent, min_broker_balance, min_profit_for_split FROM server_account LIMIT 1");
            $stmtConfig->execute();
            $config = $stmtConfig->fetch(PDO::FETCH_ASSOC);
            $MIN_INITIAL_DEPOSIT = $config ? (float)$config['minimum_deposit'] : 0;
            $CONTRACT_DURATION = $config ? (int)$config['contract_duration'] : 30;
            $MIN_PROFIT_FOR_SPLIT = $config ? (float)$config['min_profit_for_split'] : 100;
            
            if ($executionStartDate && $executionStartDate !== '0000-00-00' && $executionStartDate !== null) {
                $start = new DateTime($executionStartDate);
                $formatted_start_date = $start->format('M d, Y');
                
                $end = clone $start;
                $end->modify("+{$CONTRACT_DURATION} days");
                $formatted_end_date = $end->format('M d, Y');
                
                $today = new DateTime();
                $today->setTime(0, 0, 0);
                $end_clone = clone $end;
                $end_clone->setTime(0, 0, 0);
                
                $interval = $today->diff($end_clone);
                $contractDaysLeft = (int)$interval->format('%r%a');
                
                if ($contractDaysLeft <= 0) {
                    $contract_completed = true;
                    $is_contract_active = false;
                } else {
                    $is_contract_active = true;
                }
            }
            
            // ===== CORRECTED PRIORITY ORDER: RESET=1 COMES FIRST =====
            
            $loyalties_message = "";
            $loyalty_text = "";
            $show_reenroll_button = false;
            $show_apply_button = false;
            $show_reset_button = false;
            $show_payment_note = false;
            $show_payment_failed = false;
            $loyalty_btn_text = "";
            $loyalty_btn_class = "";
            $loyalty_btn_action = "";
            $dashboard_disclaimer = "";
            $balance_check_failed = false;
            
            // PRIORITY 0: RESET BUTTON STATE (HIGHEST PRIORITY)
            // Check if reset_contract == 1 - Show Reset button FIRST
            if ($resetContractStatus == 1) {
                $show_reset_button = true;
                $show_apply_button = false;
                $show_reenroll_button = false;
                $loyalties_message = "Ready for a new Contract?";
                $loyalty_text = "Your path is clear. Click below to embark on your next contract.";
                $dashboard_disclaimer = "Time for the Next Phase!";
                $loyalty_btn_text = "Let's get started";
                $loyalty_btn_class = "btn-loyalty-action btn-reset";
                $loyalty_btn_action = "reset";
            }
            // PRIORITY 1: APPLY FOR VERIFICATION (only if reset_contract == 0 AND not verified)
            elseif ($resetContractStatus == 0 && ($balanceVerificationStatus === 'not-verified' || empty($balanceVerificationStatus))) {
                $show_reset_button = false;
                $show_apply_button = true;
                $show_reenroll_button = false;
                $loyalties_message = "Balance Verification Required";
                $loyalty_text = "Please apply for verification now if you have deposited funds.";
                $dashboard_disclaimer = "Balance verification required. Apply if you have funded your broker account.";
                $loyalty_btn_text = "Apply for Verification";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "apply";
            }
            // PRIORITY 2: UNDER VERIFICATION
            elseif ($balanceVerificationStatus === 'applied-for-verification') {
                $show_reset_button = false;
                $show_apply_button = false;
                $show_reenroll_button = false;
                $loyalties_message = "Balance Verification Pending";
                $loyalty_text = "Your account is pending balance review. This check usually takes between 24 and 48 hours.";
                $dashboard_disclaimer = "Balance verification in progress.";
                $loyalty_btn_text = "Under Review";
                $loyalty_btn_class = "btn-loyalty-paid";
                $loyalty_btn_action = "";
            }
            // PRIORITY 3: ENROLL (only when verified AND reset_contract == 0)
            elseif ($resetContractStatus == 0 && $balanceVerificationStatus === 'verified' && $brokerBalance >= $MIN_INITIAL_DEPOSIT) {
                // Check payment and contract states
                if ($loyaltiesStatus === 'payment-made') {
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $loyalties_message = "Payment Pending Confirmation";
                    $loyalty_text = "Your payment has been recorded. Once confirmed, you can enroll for a new contract.";
                    $show_payment_note = true;
                    $show_payment_failed = false;
                    $loyalty_btn_text = "Awaiting Confirmation";
                    $loyalty_btn_class = "btn-loyalty-paid";
                    $loyalty_btn_action = "";
                    $dashboard_disclaimer = "Payment submitted for verification.";
                }
                elseif ($loyaltiesStatus === 'payment-confirmed') {
                    $dashboard_disclaimer = "Ready to start a new contract.";
                    $loyalty_text = "Your payment has been confirmed. You can now start a new trading contract.";
                    $loyalties_message = "Ready to enroll";
                    $show_reenroll_button = true;
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $show_payment_failed = false;
                    $loyalty_btn_text = "Enroll";
                    $loyalty_btn_class = "btn-loyalty-action";
                    $loyalty_btn_action = "enroll";
                }
                elseif ($loyaltiesStatus === 'payment-failed' || $loyaltiesStatus === 'failed-payment') {
                    $dashboard_disclaimer = "⚠ Payment verification failed!";
                    $loyalty_text = "Your payment could not be verified. ";
                    $loyalties_message = "Payment Failed";
                    $show_payment_note = false;
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $show_reenroll_button = false;
                    $show_payment_failed = true;
                    $loyalty_btn_text = "Retry Payment";
                    $loyalty_btn_class = "btn-loyalty-action";
                    $loyalty_btn_action = "payment-failed";
                }
                elseif ($loyaltiesStatus === 'justjoined') {
                    $loyalties_message = "Welcome New Member!";
                    $loyalty_text = "Welcome aboard! Click Enroll to start your trading journey.";
                    $show_reenroll_button = true;
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $show_payment_failed = false;
                    $loyalty_btn_text = "Enroll";
                    $loyalty_btn_class = "btn-loyalty-action";
                    $loyalty_btn_action = "enroll";
                    $dashboard_disclaimer = "Welcome to HarvHub!";
                }
                elseif ($is_contract_active) {
                    $loyalties_message = "Contract Active";
                    $loyalty_text = $contractDaysLeft . " days left.";
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $show_reenroll_button = false;
                    $show_payment_failed = false;
                    $loyalty_btn_text = "Active";
                    $loyalty_btn_class = "btn-loyalty-confirmed";
                    $loyalty_btn_action = "";
                    $dashboard_disclaimer = "Trading is active. {$contractDaysLeft} days left.";
                }
                elseif ($contract_completed) {
                    if ($loyaltiesStatus === 'payment-failed' || $loyaltiesStatus === 'failed-payment') {
                        $dashboard_disclaimer = "⚠ Payment verification failed!";
                        $loyalty_text = "Your payment could not be verified. ";
                        $loyalties_message = "Payment Failed";
                        $show_payment_note = false;
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_reenroll_button = false;
                        $show_payment_failed = true;
                        $loyalty_btn_text = "Retry Payment";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "payment-failed";
                    }
                    elseif ($profitAndLoss > $MIN_PROFIT_FOR_SPLIT && $loyaltiesStatus !== 'payment-made' && $loyaltiesStatus !== 'payment-confirmed') {
                        $loyalties_message = "Contract Ended - Payment Required";
                        $loyalty_text = "Your contract has ended with a profit of $" . number_format($profitAndLoss, 2) . ". Please complete the profit split.";
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_payment_failed = false;
                        $loyalty_btn_text = "View Profit Split";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "profitsplit";
                        $dashboard_disclaimer = "Contract completed - Profit split required!";
                    }
                    elseif ($profitAndLoss < 0) {
                        $loyalties_message = "Ready for New Contract";
                        $loyalty_text = "Don't give up! Every loss is a learning opportunity. Click Enroll to start a new contract.";
                        $show_reenroll_button = true;
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_payment_failed = false;
                        $loyalty_btn_text = "Enroll";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "enroll";
                        $dashboard_disclaimer = "Contract completed with loss. You can start a new contract.";
                    }
                    elseif ($profitAndLoss > 0 && $profitAndLoss <= $MIN_PROFIT_FOR_SPLIT) {
                        $loyalties_message = "Ready for New Contract";
                        $loyalty_text = "Profit of $" . number_format($profitAndLoss, 2) . " is below the split threshold. You keep 100% of the profit. Click Enroll to start a new contract.";
                        $show_reenroll_button = true;
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_payment_failed = false;
                        $loyalty_btn_text = "Enroll";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "enroll";
                        $dashboard_disclaimer = "Contract completed. Profit below split threshold - no profit split required.";
                    }
                    elseif ($profitAndLoss == 0) {
                        $loyalties_message = "Ready for New Contract";
                        $loyalty_text = "Your contract has ended with no profit. Click Enroll to start a new contract.";
                        $show_reenroll_button = true;
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_payment_failed = false;
                        $loyalty_btn_text = "Enroll";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "enroll";
                        $dashboard_disclaimer = "Contract completed with no profit. You can enroll for a new contract.";
                    }
                    else {
                        $loyalties_message = "Ready for New Contract";
                        $loyalty_text = "Ready to start a new contract. Click Enroll to begin.";
                        $show_reenroll_button = true;
                        $show_reset_button = false;
                        $show_apply_button = false;
                        $show_payment_failed = false;
                        $loyalty_btn_text = "Enroll";
                        $loyalty_btn_class = "btn-loyalty-action";
                        $loyalty_btn_action = "enroll";
                        $dashboard_disclaimer = "Ready to start a new contract.";
                    }
                }
                else {
                    $loyalties_message = "Ready to Start";
                    $loyalty_text = "Click Enroll to start a new trading contract.";
                    $show_reenroll_button = true;
                    $show_reset_button = false;
                    $show_apply_button = false;
                    $show_payment_failed = false;
                    $loyalty_btn_text = "Enroll";
                    $loyalty_btn_class = "btn-loyalty-action";
                    $loyalty_btn_action = "enroll";
                    $dashboard_disclaimer = "No active contract.";
                }
            }
            // PRIORITY 4: FALLBACK - Default state
            else {
                $loyalties_message = "Ready to Start";
                $loyalty_text = "Click Enroll to start a new trading contract.";
                $show_reenroll_button = true;
                $show_reset_button = false;
                $show_apply_button = false;
                $show_payment_failed = false;
                $loyalty_btn_text = "Enroll";
                $loyalty_btn_class = "btn-loyalty-action";
                $loyalty_btn_action = "enroll";
                $dashboard_disclaimer = "No active contract.";
            }
            
            echo json_encode([
                'success' => true,
                'deposit_balance' => number_format($brokerBalance, 2),
                'profit_loss' => number_format($profitAndLoss, 2),
                'current_balance' => number_format($currentBalance, 2),
                'profit_loss_class' => $profitAndLoss >= 0 ? 'profit-positive' : 'profit-negative',
                'current_balance_class' => $currentBalance >= 0 ? 'profit-positive' : 'profit-negative',
                'contract_days_left' => $is_contract_active ? $contractDaysLeft : 0,
                'is_contract_active' => $is_contract_active,
                'contract_completed' => $contract_completed,
                'formatted_start_date' => $formatted_start_date,
                'formatted_end_date' => $formatted_end_date,
                'loyalties_status' => $loyaltiesStatus,
                'balance_verification_status' => $balanceVerificationStatus,
                'reset_contract' => $resetContractStatus,
                'show_reset_button' => $show_reset_button,
                'loyalties_message' => $loyalties_message,
                'loyalty_text' => $loyalty_text,
                'show_reenroll_button' => $show_reenroll_button,
                'show_apply_button' => $show_apply_button,
                'show_payment_note' => $show_payment_note,
                'loyalty_btn_text' => $loyalty_btn_text,
                'loyalty_btn_class' => $loyalty_btn_class,
                'loyalty_btn_action' => $loyalty_btn_action,
                'dashboard_disclaimer' => $dashboard_disclaimer,
                'broker' => $broker,
                'profit_to_split' => number_format(max(0, $profitAndLoss), 2),
                'balance_check_failed' => $balance_check_failed,
                'min_initial_deposit' => $MIN_INITIAL_DEPOSIT
            ]);
        } else {
            echo json_encode(['error' => 'User not found']);
        }
        exit;
    }
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HarvHub</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes, viewport-fit=cover">
<?php include 'style.php'; ?>

</head>
<body>
    <!-- Notification Bell -->
    <div class="notification-container">
        <div class="notification-bell" onclick="toggleNotifications()">
            <i>🔔</i>
            <?php 
                // Calculate unread count from notifications
                $initialUnreadCount = 0;
                $allNotifications = [];

                if (!empty($user['notifications'])) {
                    $notificationsData = json_decode($user['notifications'], true);
                    if (is_array($notificationsData)) {
                        foreach ($notificationsData as $id => $notification) {
                            // Count unread (update == 'new')
                            if (isset($notification['update']) && $notification['update'] === 'new') {
                                $initialUnreadCount++;
                            }
                            
                            // Sanitize message - remove special characters
                            $message = $notification['message'] ?? '';
                            $message = preg_replace('/^[\?\?]+\s*/', '', $message);
                            $message = preg_replace('/[\?\?]/', '', $message);
                            $message = preg_replace('/[\x{1F300}-\x{1F6FF}]/u', '', $message);
                            
                            // Store for display
                            $allNotifications[] = [
                                'id' => $id,
                                'section' => $notification['section'] ?? 'General',
                                'message' => trim($message),
                                'time' => $notification['time'] ?? date('Y-m-d H:i:s'),
                                'type' => $notification['type'] ?? 'info',
                                'update' => $notification['update'] ?? 'read'
                            ];
                        }
                        
                        // Sort by time (newest first)
                        usort($allNotifications, function($a, $b) {
                            return strtotime($b['time']) - strtotime($a['time']);
                        });
                    }
                }
            ?>
            <?php if ($initialUnreadCount > 0): ?>
                <span class="notification-badge" id="notificationBadge"><?= $initialUnreadCount ?></span>
            <?php else: ?>
                <span class="notification-badge" id="notificationBadge" style="display: none;">0</span>
            <?php endif; ?>
        </div>
        
        <div class="notification-panel" id="notificationPanel">
            <div class="notification-header">
                <h3>📬 Notifications</h3>
                <button class="close-notifications" onclick="toggleNotifications()">✕</button>
            </div>
            <div class="notification-list" id="notificationList">
                <?php if (count($allNotifications) > 0): ?>
                    <?php foreach ($allNotifications as $notification): 
                        // Sanitize message before display
                        $cleanMessage = $notification['message'];
                        // Remove special characters from the message
                        $cleanMessage = preg_replace('/^[\?\?]+\s*/', '', $cleanMessage);
                        $cleanMessage = preg_replace('/[\?\?]/', '', $cleanMessage);
                        // Also remove any other special icon characters
                        $cleanMessage = preg_replace('/[\x{1F300}-\x{1F6FF}]/u', '', $cleanMessage);
                    ?>
                        <div class="notification-item <?= ($notification['update'] === 'new') ? 'unread' : '' ?> <?= htmlspecialchars($notification['type']) ?>"
                            data-id="<?= htmlspecialchars($notification['id']) ?>"
                            data-update="<?= htmlspecialchars($notification['update']) ?>">
                            <div class="notification-section"><?= htmlspecialchars($notification['section']) ?></div>
                            <div class="notification-message"><?= htmlspecialchars(trim($cleanMessage)) ?></div>
                            <div class="notification-time"><?= date('M d, H:i', strtotime($notification['time'])) ?></div>
                        </div>
                    <?php endforeach; ?>
                <?php else: ?>
                    <div class="empty-notifications">No notifications</div>
                <?php endif; ?>
            </div>
        </div>
    </div>
    <div class="custom-body">
        <?php if ($show_passkey_form): ?>
            <div class="passkey-overlay">
                <div class="passkey-screen">
                    <h2>Create Your Passkey</h2>
                    <p style="margin:1.5rem 0; opacity:0.9;">Secure your HarvHub access</p>
                    <form method="POST">
                        <input type="password" name="new_passkey" placeholder="Enter strong passkey" required autofocus>
                        <input type="password" name="confirm_passkey" placeholder="Confirm passkey" required style="margin-top: 10px;">
                        <?php if ($passkey_error_msg): ?>
                            <p class="error-message" style="color: #ff6b6b; margin-top: 10px;"><?= htmlspecialchars($passkey_error_msg) ?></p>
                        <?php endif; ?>
                        <button type="submit" name="create_passkey" class="btn-full" style="margin-top: 20px;">Save & Continue</button>
                    </form>
                </div>
            </div>
        <?php elseif (!$passkey_verified): ?>
            <div class="passkey-overlay">
                <div class="passkey-screen">
                    <h2>Welcome Back</h2>
                    <p style="margin:1.5rem 0; opacity:0.9;">Enter your passkey to access dashboard</p>
                    <form method="POST">
                        <input type="password" name="passkey" placeholder="Your passkey" required autofocus>
                        <?php if ($passkey_error): ?>
                            <p class="error-message" style="color: #ff6b6b; margin-top: 10px;"><?= htmlspecialchars($passkey_error) ?></p>
                        <?php endif; ?>
                        <button type="submit" name="verify_passkey" class="btn-full">Enter Dashboard</button>
                    </form>
                    <a href="forgot_passkey.php?source=dashboard" style="display:block; margin:20px 0; color:var(--accent); font-size:0.95rem;">Forgot passkey?</a>
                    <p><a href="?logout=1" style="color:#ff6b6b;">← Logout</a></p>
                </div>
            </div>
        <?php endif; ?>

        <div class="dashboard-wrapper <?= $balanceDisplay === 'hide' && $passkey_verified ? 'blur-mode' : '' ?>">
            <h1>🌾HarvHub</h1>
            <p class="welcome">Hello, <strong><?= htmlspecialchars($fullName) ?></strong></p>

            <?php if (!empty($dashboard_disclaimer)): ?>
                <p class="dashboard-disclaimer">
                    <?= htmlspecialchars($dashboard_disclaimer) ?>
                    <?php if ($loyaltiesStatus === 'unpaid-payment'): ?>
                        <span class="payment-required-badge">Payment Required</span>
                    <?php endif; ?>
                </p>
            <?php endif; ?>
            
            <?php if ($contract_completed && $profitAndLoss <= $MIN_PROFIT_FOR_SPLIT && $profitAndLoss > 0): ?>
                <div class="threshold-warning">
                    ⚠️ Your profit of $<?= number_format($profitAndLoss, 2) ?> is below the minimum split threshold of $<?= number_format($MIN_PROFIT_FOR_SPLIT, 2) ?>. No profit split required - you can enroll directly.
                </div>
            <?php endif; ?>

            <?php if ($profitAndLoss < 0 && $contract_completed): ?>
                <p class="encouragement-note">
                    Don't give up! Every loss is a setup for a greater comeback. Your next contract could be your breakthrough!
                </p>
            <?php endif; ?>

            <div class="stats-grid">
                <div class="stat-card">
                    <form method="POST" style="margin:0;">
                        <input type="hidden" name="toggle_balance_display" value="1">
                        <button type="submit" title="<?= $balanceDisplay === 'show' ? 'Hide Balance' : 'Show Balance' ?>" class="balance-toggle-btn">
                            <?php if ($balanceDisplay === 'show'): ?>
                                👁️
                            <?php else: ?>
                                🔒 
                            <?php endif; ?>
                        </button>
                    </form>
                    
                    <h3> STARTING BALANCE</h3>
                    <div class="stat-details-info">
                        <?= htmlspecialchars($login) ?>
                        <?= htmlspecialchars($server) ?>
                    </div>
                    <?php if ($balance_unverified): ?>
                        <div class="stat-details-info" style="color: var(--warning);">
                            Unverified
                        </div>
                    <?php elseif ($balance_under_verification): ?>
                        <div class="stat-details-info" style="color: var(--info);">
                            Under Review
                        </div>
                    <?php elseif ($balance_check_failed): ?>
                        <div class="stat-details-info" style="color: var(--warning);">
                            Minimum deposit of $<?= number_format($MIN_INITIAL_DEPOSIT, 2) ?> required.
                        </div>
                    <?php else: ?>
                        <h2>$<?= number_format($depositBalance, 2) ?></h2>
                        <div class="stat-details-info">
                            Verified Account
                        </div>
                    <?php endif; ?>
                    
                    <!-- NEW: Revenue History Button -->
                    <button type="button" class="btn-revenue-history" onclick="openRevenueHistoryModal()">
                        View Revenue History
                    </button>
                </div>
                
                <div class="stat-card">
                    <h3>Profit & Loss</h3>
                    <h2 class="<?= $profitAndLoss >= 0 ? 'profit-positive' : 'profit-negative' ?>">
                        $<?= number_format($profitAndLoss, 2) ?>
                    </h2>
                    <div class="stat-details-info">
                        Yield
                    </div>
                </div>

                <div class="stat-card">
                    <h3>Current Balance</h3>
                    <h2 class="<?= $currentBalance >= 0 ? 'profit-positive' : 'profit-negative' ?>">
                        $<?= number_format($currentBalance, 2) ?>
                    </h2>
                    <div class="stat-details-info">
                        Harvest
                    </div>
                </div>
                
                <div class="stat-card loyalty-card">
                    <span class="loyalty-status-msg"><?= htmlspecialchars($loyalties_message) ?></span>
                    <p><?= htmlspecialchars($loyalty_text) ?></p>

                    <?php if ($is_contract_active && $executionStartDate && $executionStartDate !== '0000-00-00'): ?>
                        <span class="contract-dates">
                            Started: <?= htmlspecialchars($formatted_start_date) ?> | Ends: <?= htmlspecialchars($formatted_end_date) ?>
                        </span>
                    <?php endif; ?>
                    
                    <?php if ($is_contract_active): ?>
                        <p><?= $CONTRACT_DURATION ?> days contract duration</p>
                    <?php endif; ?>
                    
                    <?php if ($MIN_PROFIT_FOR_SPLIT > 0): ?>
                        <small style="opacity:0.6;">Min profit for split: $<?= number_format($MIN_PROFIT_FOR_SPLIT, 2) ?></small>
                    <?php endif; ?>
                    
                    <!-- ONLY SHOW ENROLL/ACTION BUTTON WHEN NOT IN APPLY MODE AND NOT IN PAYMENT NOTE MODE -->
                    <!-- BUTTON ORDER: Reset -> Apply -> Enroll -->
                    <!-- RESET BUTTON (show when reset_contract = 0) -->
                    <?php if ($show_reset_button && !$show_payment_note): ?>
                        <button 
                            onclick="openResetModal()"
                            class="btn-loyalty-action btn-reset"
                        >
                            Let's Get Started
                        </button>
                    <?php endif; ?>

                    <!-- APPLY BUTTON (show when reset_contract = 1 AND unverified) -->
                    <?php if ($show_apply_button && !$show_payment_note): ?>
                        <button 
                            onclick="openApplyModal()"
                            class="btn-loyalty-action"
                            style="margin-top: 1rem; width: 100%;"
                        >
                            Apply for Verification
                        </button>
                    <?php endif; ?>

                    <!-- ENROLL/ACTION BUTTON (show when NOT in reset/apply mode) -->
                    <?php if (!$show_reset_button && !$show_apply_button && !$show_payment_note): ?>
                        <button 
                            <?= $loyalty_btn_action ?>
                            class="<?= htmlspecialchars($loyalty_btn_class) ?>"
                            <?= ($loyalty_btn_class === 'btn-loyalty-paid' && $loyalty_btn_text !== 'Awaiting Confirmation') ? 'disabled' : '' ?>
                        >
                            <?= htmlspecialchars($loyalty_btn_text) ?>
                        </button>
                    <?php endif; ?>
                </div>
            </div>
            <div class="note-btndanger">
                <div class="note-btndanger-block">
                    <button class="btn-danger" onclick="openDisconnectModal()">
                        Disconnect My Account
                    </button>
                    <p class="logout-link-p">
                    <a href="?logout=1" style="color:#ff6b6b;">← Logout</a></p>
                </div>
            </div>
                        
        </div>

        <!-- First Disconnect Confirmation Modal -->
        <div id="disconnectModal" class="modal">
            <div class="modal-content">
                <h2 style="color:#ff6b6b;">⚠ Disconnect Account?</h2>
                <p style="margin:1.5rem 0; line-height:1.6;">
                    This action will disconnect your account from trading activities permanently.
                </p>
                <div class="modal-actions"> 
                    <button onclick="this.closest('.modal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Cancel
                    </button>
                    <button onclick="closeDisconnectModalAndOpenFinal()"
                        style="background:#e74c3c; color:white; border:none;">
                        Continue to Verification
                    </button>
                </div>
            </div>
        </div>

        <!-- Final Disconnect Verification Modal -->
        <div id="finalDisconnectModal" class="modal">
            <div class="modal-content">
                <h2 style="color:#ff6b6b;"> Final Verification Required</h2>
                <p style="margin:0.5rem 0 1rem 0; opacity:0.8; font-size:0.9rem;">
                    Please confirm your broker credentials and passkey to proceed with disconnection.
                </p>
                
                <?php if ($disconnect_errors): ?>
                    <div class="disconnect-errors">
                        <ul>
                            <?php foreach ($disconnect_errors as $error): ?>
                                <li><?= htmlspecialchars($error) ?></li>
                            <?php endforeach; ?>
                        </ul>
                    </div>
                <?php endif; ?>
                
                <form method="POST" id="finalDisconnectForm">
                    <input type="hidden" name="final_disconnect_confirm" value="1">
                    
                    <div class="disconnect-verify-section">
                        <label> Server</label>
                        <input type="text" name="verify_server" placeholder="Enter your server name" required autocomplete="off">
                        
                        <label> Login ID</label>
                        <input type="text" name="verify_login" placeholder="Enter your login ID" required autocomplete="off">
                        
                        <label> Password</label>
                        <input type="password" name="verify_password" placeholder="Enter your broker password" required autocomplete="off">
                        
                        <label> Dashboard Passkey</label>
                        <input type="password" name="verify_passkey" placeholder="Enter your dashboard passkey" required autocomplete="off">
                    </div>
                    
                    <div class="disconnect-warning-note">
                        <strong> Important Notice:</strong><br>
                        Your broker credentials (Server, Login, Password) and dashboard passkey will be permanently deleted from our system upon confirmation.
                    </div>
                    
                    <div class="modal-actions-vertical">
                        <button type="submit" class="btn-danger-final" id="finalDisconnectBtn">
                            Permanently Disconnect Account
                        </button>
                        <button type="button" class="btn-cancel-final" onclick="closeFinalDisconnectModal()">
                            Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Profit Split Modal -->
        <div id="profitSplitModal" class="modal">
            <div class="modal-content">
                <h2 style="color:var(--info-color);">Profit Split Required</h2>
                
                <p style="margin-bottom: 2rem; opacity: 0.8;">
                    Your contract has ended with a profit of $<?= number_format($profitToSplit, 2) ?>.
                </p>
                
                <?php if ($loyaltiesStatus === 'unpaid-payment'): ?>
                    <div class="unpaid-warning" style="margin-bottom: 1rem; background: rgba(255, 107, 107, 0.2);">
                        <strong>Server %:</strong> You are expected to send payment of $<?= number_format($serverShare, 2) ?> to the server.
                    </div>
                <?php endif; ?>
                <div class="split-container">
                    <div class="split-item">
                        <h4 style="color:var(--success-color);"><?= $USER_SHARE_PERCENT ?>%</h4>
                        <p>Your Share</p>
                        <h4 style="color:var(--success-color);">$<?= number_format($userShare, 2) ?></h4>
                        <button class="btn-withdraw" 
                                onclick="window.open('<?= $brokerTarget ?>', '_blank')"
                                style="background:#2ecc71; color:white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px; display: block; width: 100%;">
                            Withdraw Your Share
                        </button>
                        <small style="display:block; margin-top:10px; opacity:0.6;">Withdraw your $<?= number_format($userShare, 2) ?> profit share</small>
                    </div>
                    <div class="split-item">
                        <h4 style="color:var(--success-color);"><?= $SERVER_SHARE_PERCENT ?>%</h4>
                        <p>Server Share</p>
                        <h4 style="color:var(--success-color);">$<?= number_format($serverShare, 2) ?></h4>
                        <button class="btn-pay" onclick="updateServerShareAmount(); document.getElementById('profitSplitModal').classList.remove('active');       document.getElementById('paymentModal').classList.add('active');"
                                style="padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px; display: block; width: 100%;">
                            Pay Server Share
                        </button>
                        <small style="display:block; margin-top:10px; opacity:0.6;">Pay $<?= number_format($serverShare, 2) ?> to remain eligible</small>
                    </div>
                </div>

                <div class="modal-actions">
                    <button onclick="this.closest('.modal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Close
                    </button>
                </div>
            </div>
        </div>

        <!-- Payment Modal -->
        <div id="paymentModal" class="modal">
            <div class="modal-content">
                <h2 style="color:var(--accent);">Pay Server Share</h2>
                <p style="margin:1rem 0; opacity:0.8;">
                    Send <strong id="paymentAmountDisplay">$<?= number_format($serverShare, 2) ?></strong> worth of the selected cryptocurrency
                </p>
                
                <input type="hidden" id="serverShareAmountHidden" value="<?= number_format($serverShare, 2, '.', '') ?>">

                <div class="coin-selector">
                    <input type="radio" id="coin_btc" name="coin" value="btc" checked onchange="updatePaymentDetails('btc')">
                    <label for="coin_btc">BTC</label>
                    
                    <input type="radio" id="coin_eth" name="coin" value="eth" onchange="updatePaymentDetails('eth')">
                    <label for="coin_eth">ETH</label>

                    <input type="radio" id="coin_usdt" name="coin" value="usdt" onchange="updatePaymentDetails('usdt')">
                    <label for="coin_usdt">USDT</label>
                </div>

                <div class="crypto-details">
                    <p>Network: <strong id="paymentNetwork">N/A</strong></p>
                    <p>Address:</p>
                    <span class="btc-address" id="paymentAddress">N/A</span>
                </div>
                
                <button class="btn-full btn-paid" id="copyAddressBtn">
                    Copy Address
                </button>

                <label class="checkbox-container">
                    <input type="checkbox" id="paymentConfirmationCheck" onchange="togglePaidButton()">
                    I have made the payment
                </label>

                <button class="btn-full btn-paid" id="confirmPaidBtn" disabled onclick="triggerFinalConfirmation()">
                    Confirm Payment
                </button>
                
                <p class="disclaimer">Click only after payment has been successfully sent. Your payment will be verified by the server.</p>
                
                <div class="modal-actions">
                    <button onclick="this.closest('.modal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Cancel
                    </button>
                </div>
            </div>
        </div>
        <!-- Payment Failed Modal -->
        <div id="paymentFailedModal" class="modal">
            <div class="modal-content">
                <h2 style="color: #ff6b6b;">⚠ Payment Failed</h2>

                <p style="margin: 1rem 0; opacity: 0.8;">
                    Your contract ended with a profit of <strong>$<?= number_format($profitToSplit, 2) ?></strong>.
                </p>
                
                <div class="payment-failed-warning" style="background: rgba(255, 107, 107, 0.15); border-left: 4px solid #ff6b6b; padding: 1rem; margin: 1rem 0;">
                    <p style="margin-top: 0.5rem; opacity: 0.8;">
                        The server did not receive confirmation of $<?= number_format($serverShare, 2) ?> payment you made.
                    </p>
                </div>

                <div class="split-container">
                    <div class="split-item">
                        <h4 style="color:var(--success-color);"><?= $SERVER_SHARE_PERCENT ?>%</h4>
                        <p>Server Share</p>
                        <h4 style="color:var(--success-color);">$<?= number_format($serverShare, 2) ?></h4>
                        <button class="btn-pay" onclick="updateServerShareAmount(); document.getElementById('paymentFailedModal').classList.remove('active'); document.getElementById('paymentModal').classList.add('active');"
                                style="padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px; display: block; width: 100%; background: #ff9800; color: white;">
                            Retry Payment
                        </button>
                    </div>
                </div>

                <div class="modal-actions">
                    <button onclick="this.closest('.modal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Close
                    </button>
                </div>
            </div>
        </div>

        <!-- Final Confirmation Modal -->
        <div id="finalConfirmationModal" class="modal">
            <div class="modal-content">
                <h2 style="color:var(--success-color);">Final Confirmation</h2>
                <p style="margin:1.5rem 0; line-height:1.6;">
                    Confirm that you have sent <strong id="finalConfirmAmount" style="color:var(--success-color);">$<?= number_format($serverShare, 2) ?></strong> to the 
                    <strong id="finalConfirmCoin">N/A</strong> address.
                </p>
                
                <div class="modal-actions"> 
                    <button onclick="document.getElementById('finalConfirmationModal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Cancel
                    </button>
                    <form method="POST" style="display:inline;" id="finalPaymentForm">
                        <input type="hidden" name="final_confirm_payment" value="1">
                        <input type="hidden" name="server_share_amount" id="formServerShareAmount" value="<?= number_format($serverShare, 2, '.', '') ?>">
                        <input type="hidden" name="payment_coin" id="formPaymentCoin" value="">
                        <button type="submit" id="finalConfirmButton"
                            style="background:rgba(0, 130, 18, 0.95); color:white; border:none;">
                            Yes, I've Paid
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <!-- enrollment Modal with Instructions -->
        <div id="reenrollModal" class="modal">
            <div class="modal-content">
                <h2 style="color:var(--info-color);">Contract enrollment Protocol</h2>
                
                <p style="margin:1rem 0; opacity:0.8; font-size:0.95rem;">
                    You are about to commence a new <?= $CONTRACT_DURATION ?>-day trading contract. 
                    Please carefully review the following stipulations before proceeding.
                </p>
                
                <div class="reenroll-instructions">
                    <h4>⚠ Enrollment Terms</h4>
                    <ul>
                        <li>
                            <strong>No Manual Trading:</strong> Do not open, close, or modify any trades 
                            manually during the automation period.
                        </li>
                        <li>
                            <strong>No Withdrawals:</strong> Do not withdraw profits or balance from your 
                            MT5 account until the contract expires.
                        </li>
                        <li>
                            <strong>No Deposits:</strong> Do not deposit or transfer funds from external 
                            wallets to your broker account during this period.
                        </li>
                    </ul>
                    <div class="consequence-note">
                        Violation of any of these terms will result in permanent disqualification from the programme.
                    </div>
                </div>
                
                <label class="checkbox-container-legal" id="reenrollCheckContainer">
                    <input type="checkbox" id="reenrollConfirmCheck" onchange="toggleReenrollButton()">
                    <label for="reenrollConfirmCheck">
                        I understand the terms.
                    </label>
                </label>
                
                <div class="modal-actions" style="flex-direction: column; gap: 10px;">
                    <button id="reenrollProceedBtn" 
                            class="reenroll-confirm-btn" 
                            disabled 
                            onclick="proceedToPasskeyVerification()">
                        Proceed to Verification
                    </button>
                    <button onclick="closeReenrollModal()"
                        style="width: 100%; padding: 12px; background:#555; color:white; border:none; border-radius: 8px; cursor: pointer;">
                        Cancel
                    </button>
                </div>
            </div>
        </div>

        <!-- Passkey Verification Overlay for enrollment -->
        <div id="reenrollPasskeyOverlay" class="passkey-verification-overlay">
            <div class="passkey-verification-box">
                <h3> Identity Verification Required</h3>
                <p style="margin:1rem 0; opacity:0.8;">
                    To finalize your enrollment, please enter your dashboard passkey to confirm your identity.
                </p>
                
                <input type="password" id="reenrollPasskeyInput" placeholder="Enter your passkey" autocomplete="off">
                
                <p class="error-message" id="reenrollPasskeyError">
                    Incorrect passkey. Please try again.
                </p>
                
                <button id="verifyReenrollPasskeyBtn" class="btn-verify-passkey" onclick="verifyReenrollPasskey()">
                    Verify & Confirm
                </button>
                
                <button class="btn-cancel" onclick="closeReenrollPasskeyOverlay()">
                    Cancel
                </button>
            </div>
        </div>

        <!-- Hidden enrollment Form -->
        <form id="reenrollForm" method="POST" style="display:none;">
            <input type="hidden" name="confirm_reenroll" value="1">
        </form>

        <!-- Trade History Modal -->
        <div id="tradeHistoryModal" class="modal">
            <div class="modal-content">
                <h2>Trade History Summary</h2>
                <p style="margin:1rem 0; opacity:0.8;">Currency pairs that won/lost</p>

                <h3 style="color:var(--success-color); margin-top:2rem;">Won Trades (<?= count($tradesData['symbolsthatwon']) ?> Symbols)</h3>
                <div class="history-section">
                    <?php if (!empty($tradesData['symbolsthatwon'])): ?>
                        <?php foreach ($tradesData['symbolsthatwon'] as $trade): ?>
                            <div class="history-item">
                                <span class="history-symbol"><?= $trade['symbol'] ?></span>
                                <span class="history-amount-won">+<?= ltrim($trade['amount'], '+-') ?></span>
                            </div>
                        <?php endforeach; ?>
                    <?php else: ?>
                        <p style="text-align: center; opacity: 0.7;">No winning symbol data available.</p>
                    <?php endif; ?>
                </div>
                
                <h3 style="color:var(--error-color); margin-top:2rem;">Lost Trades (<?= count($tradesData['symbolsthatlost']) ?> Symbols)</h3>
                <div class="history-section">
                    <?php if (!empty($tradesData['symbolsthatlost'])): ?>
                        <?php foreach ($tradesData['symbolsthatlost'] as $trade): ?>
                            <div class="history-item">
                                <span class="history-symbol"><?= $trade['symbol'] ?></span>
                                <span class="history-amount-lost"><?= $trade['amount'] ?></span>
                            </div>
                        <?php endforeach; ?>
                    <?php else: ?>
                        <p style="text-align: center; opacity: 0.7;">No losing symbol data available.</p>
                    <?php endif; ?>
                </div>

                <div class="modal-actions">
                    <button onclick="this.closest('.modal').classList.remove('active')"
                        style="background:#555; color:white; border:none;">
                        Close
                    </button>
                </div>
            </div>
        </div>
        <!-- Revenue History Modal -->
        <div id="revenueHistoryModal" class="modal">
            <div class="modal-content">
                <h2>Revenue History</h2>
                <div id="revenueHistoryContainer" class="revenue-history-container">
                    <div class="empty-revenue">Loading...</div>
                </div>
                <div class="modal-actions">
                    <button onclick="closeRevenueHistoryModal()"
                        style="background:#555; color:white; border:none;">
                        Close
                    </button>
                </div>
            </div>
        </div>
    </div>
    <!-- Apply for Verification Modal -->
<div id="applyModal" class="modal">
    <div class="modal-content">
        <h2 style="color: var(--info);">Balance Verification Application</h2>
        
        <p style="margin: 1.5rem 0; line-height: 1.6;">
            Before proceeding with your application, please ensure:
        </p>
        
        <div class="apply-instructions" style="background: rgba(255, 255, 255, 0.05); padding: 1rem; border-radius: 8px; margin: 1rem 0;">
            <ul style="list-style: none; padding-left: 0;">
                <li style="margin-bottom: 10px;">✓ Your broker account is active and accessible with same login credentials</li>
                <li style="margin-bottom: 10px;">✓ You have deposited into your broker account</li>
            </ul>
        </div>
        
        <div class="apply-warning" style="background: rgba(255, 193, 7, 0.1); border-left: 4px solid #ffc107; padding: 1rem; margin: 1rem 0;">
            <strong style="color: #ffc107;">⚠ Important:</strong>
            <p style="margin-top: 0.5rem;">Ensure you have deposited into your account before confirming application.</p>
        </div>
        
        <div class="modal-actions" style="flex-direction: column; gap: 10px;">
            <form method="POST" style="width: 100%;">
                <input type="hidden" name="apply_for_verification" value="1">
                <button type="submit" class="btn-full" style="background: var(--info); color: white; width: 100%;">
                    Confirm Application
                </button>
            </form>
            <button onclick="closeApplyModal()" style="width: 100%; padding: 12px; background: #555; color: white; border: none; border-radius: 8px; cursor: pointer;">
                Cancel
            </button>
        </div>
    </div>
</div>

    <!-- Reset Contract Confirmation Modal -->
    <div id="resetModal" class="modal">
        <div class="modal-content">
            <h2 style="color: #ff9800;">Start a new Journey</h2>
            <div class="reset-note" style="background: rgba(46, 204, 113, 0.1); border-left: 4px solid #2ecc71; padding: 1rem; margin: 1rem 0;">
                <strong style="color: #2ecc71;">✅ Important:</strong>
                <p style="margin-top: 0.5rem;">Please ensure you have deposited funds into your broker account before applying for verification.</p>
            </div>
            
            <div class="modal-actions" style="flex-direction: column; gap: 10px;">
                <form method="POST" style="width: 100%;">
                    <input type="hidden" name="confirm_reset_contract" value="1">
                    <button type="submit" class="btn-loyalty-action" style="background: #ff9800; color: white; width: 100%;">
                        Continue
                    </button>
                </form>
                <button onclick="closeResetModal()" style="width: 100%; padding: 12px; background: #555; color: white; border: none; border-radius: 8px; cursor: pointer;">
                    Cancel
                </button>
            </div>
        </div>
    </div>
    <!-- Apply Success Modal -->
    <div id="applySuccessModal" class="modal">
        <div class="modal-content">
            <div class="success-icon">✅</div>
            <h2 style="color: var(--success);">Application Submitted!</h2>
            <p id="applySuccessMessage" style="margin: 1.5rem 0; font-size: 1.1rem; text-align: center;">
                Your application has been submitted successfully!
            </p>
            <p id="applySuccessDetails" style="margin: 0.5rem 0 1.5rem 0; opacity: 0.8; text-align: center; font-size: 0.95rem;">
                Our team will verify your account. Please ensure you have deposited the minimum required amount.
            </p>
            <div class="modal-actions" style="justify-content: center;">
                <button onclick="closeApplySuccessModal()" 
                        style="background: var(--success); color: white; border: none; padding: 12px 40px; border-radius: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s ease;">
                    Got it
                </button>
            </div>
        </div>
    </div>

<script>
    // This function must be available globally
    function openApplyModal() {
        const modal = document.getElementById('applyModal');
        if (modal) {
            modal.classList.add('active');
        }
    }

    function closeApplyModal() {
        const modal = document.getElementById('applyModal');
        if (modal) {
            modal.classList.remove('active');
        }
    }

    // Close apply modal when clicking outside
    document.addEventListener('click', function(event) {
        const modal = document.getElementById('applyModal');
        if (event.target === modal) {
            closeApplyModal();
        }
    });

    // Check for apply success message
    <?php if (isset($_SESSION['apply_success_message'])): ?>
        setTimeout(function() {
            const message = '<?= htmlspecialchars($_SESSION['apply_success_message']) ?>';
            const details = '<?= htmlspecialchars($_SESSION['apply_success_details'] ?? 'Our team will verify your account.') ?>';
            openApplySuccessModal(message, details);
        }, 100);
        <?php unset($_SESSION['apply_success_message']); ?>
        <?php unset($_SESSION['apply_success_details']); ?>
    <?php endif; ?>
</script>
<script>
    // Clean URL
    if (window.history.replaceState) {
        window.history.replaceState(null, null, window.location.href.split("?")[0]);
    }

    // ============== Disconnect Flow Functions ==============
    
    function openDisconnectModal() {
        document.getElementById('disconnectModal').classList.add('active');
    }
    
    function closeDisconnectModalAndOpenFinal() {
        document.getElementById('disconnectModal').classList.remove('active');
        document.getElementById('finalDisconnectModal').classList.add('active');
        // Clear any previous input values
        const form = document.getElementById('finalDisconnectForm');
        if (form) {
            form.reset();
        }
    }
    
    function closeFinalDisconnectModal() {
        document.getElementById('finalDisconnectModal').classList.remove('active');
    }
    
    // Optional: Add form validation before submit
    document.getElementById('finalDisconnectForm')?.addEventListener('submit', function(e) {
        const server = this.querySelector('[name="verify_server"]').value.trim();
        const login = this.querySelector('[name="verify_login"]').value.trim();
        const password = this.querySelector('[name="verify_password"]').value.trim();
        const passkey = this.querySelector('[name="verify_passkey"]').value.trim();
        
        if (!server || !login || !password || !passkey) {
            e.preventDefault();
            alert('Please fill in all fields to verify your identity.');
            return false;
        }
        
        // Show loading state on button
        const btn = document.getElementById('finalDisconnectBtn');
        if (btn) {
            btn.textContent = 'Verifying and Disconnecting...';
            btn.disabled = true;
        }
    });

    // ============== enrollment Flow Functions ==============
    
    function openReenrollModal() {
        // Reset states
        document.getElementById('reenrollConfirmCheck').checked = false;
        document.getElementById('reenrollProceedBtn').disabled = true;
        document.getElementById('reenrollPasskeyInput').value = '';
        document.getElementById('reenrollPasskeyError').style.display = 'none';
        document.getElementById('verifyReenrollPasskeyBtn').disabled = false;
        
        // Show enroll modal
        document.getElementById('reenrollModal').classList.add('active');
    }
    
    function closeReenrollModal() {
        document.getElementById('reenrollModal').classList.remove('active');
        closeReenrollPasskeyOverlay();
    }
    
    function toggleReenrollButton() {
        const checkbox = document.getElementById('reenrollConfirmCheck');
        const button = document.getElementById('reenrollProceedBtn');
        button.disabled = !checkbox.checked;
        
        if (checkbox.checked) {
            button.style.background = '#0080bc';
            button.style.color = '#000';
            button.style.cursor = 'pointer';
            button.style.opacity = '1';
        } else {
            button.style.background = '#555';
            button.style.color = '#999';
            button.style.cursor = 'not-allowed';
            button.style.opacity = '0.6';
        }
    }
    
    function proceedToPasskeyVerification() {
        // Close the enroll modal
        document.getElementById('reenrollModal').classList.remove('active');
        
        // Show the passkey verification overlay
        document.getElementById('reenrollPasskeyOverlay').classList.add('active');
        document.getElementById('reenrollPasskeyInput').focus();
    }
    
    function closeReenrollPasskeyOverlay() {
        document.getElementById('reenrollPasskeyOverlay').classList.remove('active');
        document.getElementById('reenrollPasskeyError').style.display = 'none';
    }
    
    function verifyReenrollPasskey() {
        const passkeyInput = document.getElementById('reenrollPasskeyInput');
        const errorElement = document.getElementById('reenrollPasskeyError');
        const verifyBtn = document.getElementById('verifyReenrollPasskeyBtn');
        
        const passkey = passkeyInput.value.trim();
        
        if (!passkey) {
            errorElement.textContent = 'Please enter your passkey.';
            errorElement.style.display = 'block';
            return;
        }
        
        // Disable button and show loading
        verifyBtn.disabled = true;
        verifyBtn.textContent = 'Verifying...';
        errorElement.style.display = 'none';
        
        // Send AJAX request to verify passkey
        fetch(window.location.href, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'verify_reenroll_passkey=1&passkey=' + encodeURIComponent(passkey)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Passkey verified - submit the enrollment form
                document.getElementById('reenrollPasskeyOverlay').classList.remove('active');
                document.getElementById('reenrollForm').submit();
            } else {
                // Show error
                errorElement.textContent = data.message || 'Incorrect passkey. Please try again.';
                errorElement.style.display = 'block';
                verifyBtn.disabled = false;
                verifyBtn.textContent = 'Verify & Confirm';
                passkeyInput.value = '';
                passkeyInput.focus();
            }
        })
        .catch(error => {
            console.error('Error:', error);
            errorElement.textContent = 'An error occurred. Please try again.';
            errorElement.style.display = 'block';
            verifyBtn.disabled = false;
            verifyBtn.textContent = 'Verify & Confirm';
        });
    }
    
    // Allow pressing Enter in passkey input
    document.getElementById('reenrollPasskeyInput').addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            verifyReenrollPasskey();
        }
    });

    // ============== Payment Selector Logic ==============
    
    const serverAccounts = {
        btc: { 
            address: "<?= htmlspecialchars($serverAccount['btc_address'] ?? 'N/A') ?>", 
            network: "Bitcoin" 
        },
        eth: { 
            address: "<?= htmlspecialchars($serverAccount['eth_address'] ?? 'N/A') ?>", 
            network: "<?= htmlspecialchars($serverAccount['eth_network'] ?? 'ERC20') ?>" 
        },
        usdt: { 
            address: "<?= htmlspecialchars($serverAccount['usdt_address'] ?? 'N/A') ?>", 
            network: "<?= htmlspecialchars($serverAccount['usdt_network'] ?? 'TRC20') ?>" 
        }
    };
            
    const paymentAddressElement = document.getElementById('paymentAddress');
    const paymentNetworkElement = document.getElementById('paymentNetwork');
    const copyAddressBtn = document.getElementById('copyAddressBtn');
    const confirmPaidBtn = document.getElementById('confirmPaidBtn');
    const paymentConfirmationCheck = document.getElementById('paymentConfirmationCheck');
    let serverShareAmountHidden = document.getElementById('serverShareAmountHidden');
            
    const finalConfirmationModal = document.getElementById('finalConfirmationModal');
    const finalConfirmAmount = document.getElementById('finalConfirmAmount');
    const finalConfirmCoin = document.getElementById('finalConfirmCoin');
    const formServerShareAmount = document.getElementById('formServerShareAmount');
    const formPaymentCoin = document.getElementById('formPaymentCoin');

    // Function to update server share amount from the current PHP value
    function updateServerShareAmount() {
        // Get the current server share from the PHP variable
        const serverShare = <?php echo number_format($serverShare, 2, '.', ''); ?>;
        if (serverShareAmountHidden) {
            serverShareAmountHidden.value = serverShare;
        }
        
        // Update the payment modal text
        const paymentDescEl = document.querySelector('#paymentModal p');
        if (paymentDescEl && paymentDescEl.innerHTML.includes('Send $')) {
            paymentDescEl.innerHTML = `Send $${serverShare.toFixed(2)} worth of the selected cryptocurrency`;
        }
    }

    function getSelectedCoin() {
        return document.querySelector('input[name="coin"]:checked').value;
    }

    function updatePaymentDetails(coin) {
        const data = serverAccounts[coin];
        if (data) {
            paymentAddressElement.textContent = data.address;
            paymentNetworkElement.textContent = data.network;
            paymentAddressElement.dataset.address = data.address;
        }
    }

    function togglePaidButton() {
        confirmPaidBtn.disabled = !paymentConfirmationCheck.checked;
    }

    function triggerFinalConfirmation() {
        const selectedCoin = getSelectedCoin();
        // Get server share from PHP value
        const serverShareAmount = <?php echo number_format($serverShare, 2, '.', ''); ?>;
        
        // Update the displayed amount in the modal
        const finalConfirmAmountSpan = document.getElementById('finalConfirmAmount');
        if (finalConfirmAmountSpan) {
            finalConfirmAmountSpan.innerHTML = '$' + serverShareAmount.toFixed(2);
        }
        
        const finalConfirmCoinSpan = document.getElementById('finalConfirmCoin');
        if (finalConfirmCoinSpan) {
            finalConfirmCoinSpan.innerHTML = selectedCoin.toUpperCase();
        }
        
        // Update form hidden inputs
        const formServerShareAmount = document.getElementById('formServerShareAmount');
        if (formServerShareAmount) {
            formServerShareAmount.value = serverShareAmount;
        }
        
        const formPaymentCoin = document.getElementById('formPaymentCoin');
        if (formPaymentCoin) {
            formPaymentCoin.value = selectedCoin;
        }
        
        // Close payment modal and open confirmation modal
        document.getElementById('paymentModal').classList.remove('active');
        document.getElementById('finalConfirmationModal').classList.add('active');
    }

    // Override the pay button click to ensure amount is correct
    document.querySelectorAll('.btn-pay').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            // Update server share amount before showing payment modal
            updateServerShareAmount();
            document.getElementById('profitSplitModal').classList.remove('active');
            document.getElementById('paymentModal').classList.add('active');
        });
    });

    copyAddressBtn.addEventListener('click', function() {
        const address = paymentAddressElement.textContent;
        if (navigator.clipboard && address && address !== 'N/A') {
            navigator.clipboard.writeText(address).then(() => {
                alert('Payment address copied to clipboard!');
            }).catch(err => {
                console.error('Could not copy text: ', err);
            });
        } else {
            alert('Address not available or clipboard access denied.');
        }
    });

    document.addEventListener('DOMContentLoaded', function() {
        updateServerShareAmount();
        updatePaymentDetails(getSelectedCoin());
        togglePaidButton();
        
        document.querySelectorAll('input[name="coin"]').forEach(radio => {
            radio.addEventListener('change', (event) => updatePaymentDetails(event.target.value));
        });
    });

    paymentAddressElement.addEventListener('click', function() {
        copyAddressBtn.click();
    });
    
    // Close modals when clicking outside
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(event) {
            if (event.target === this) {
                this.classList.remove('active');
            }
        });
    });
    
    // Close passkey overlay when clicking outside the box
    document.getElementById('reenrollPasskeyOverlay').addEventListener('click', function(event) {
        if (event.target === this) {
            closeReenrollPasskeyOverlay();
        }
    });
    
            // Close final disconnect modal when clicking outside
    document.getElementById('finalDisconnectModal').addEventListener('click', function(event) {
        if (event.target === this) {
            closeFinalDisconnectModal();
        }
    });
</script>
<script>
    // ============== LIVE BALANCE UPDATES ==============

    // Store DOM elements for performance
    const depositBalanceEl = document.querySelector('.stat-card:first-child h2');
    const profitLossEl = document.querySelector('.stat-card:nth-child(2) h2');
    const currentBalanceEl = document.querySelector('.stat-card:nth-child(3) h2');
    const loyaltyDaysLeftEl = document.querySelector('.loyalty-card p');
    const loyaltiesEl = document.querySelector('.loyalty-status-msg');

    // Track if update is in progress
    let isUpdating = false;
    let updateInterval = null;
    let retryCount = 0;
    const MAX_RETRIES = 3;

        // Function to fetch latest balances and update all UI elements
        async function fetchLiveBalances() {
            if (isUpdating) return;
            
            isUpdating = true;
            
            try {
                const response = await fetch(window.location.href, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    credentials: 'same-origin'
                });
                
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                
                const data = await response.json();
                
                if (data.success) {
                    retryCount = 0;
                    
                    // Update balance displays
                    if (depositBalanceEl && data.deposit_balance) {
                        animateValue(depositBalanceEl, depositBalanceEl.innerText.replace('$', ''), data.deposit_balance, '$');
                    }
                    
                    if (profitLossEl && data.profit_loss) {
                        animateValue(profitLossEl, profitLossEl.innerText.replace('$', ''), data.profit_loss, '$');
                        profitLossEl.className = data.profit_loss_class;
                    }
                    
                    if (currentBalanceEl && data.current_balance) {
                        animateValue(currentBalanceEl, currentBalanceEl.innerText.replace('$', ''), data.current_balance, '$');
                        currentBalanceEl.className = data.current_balance_class;
                    }
                    
                    // Update contract dates display
                    const contractDatesEl = document.querySelector('.contract-dates');
                    if (contractDatesEl && data.formatted_start_date && data.formatted_end_date) {
                        contractDatesEl.innerHTML = `Started: ${data.formatted_start_date} | Ends: ${data.formatted_end_date}`;
                    } else if (contractDatesEl && !data.formatted_start_date) {
                        contractDatesEl.style.display = 'none';
                    }
                    
                    // ===== FIXED: Update loyalty text - Always use server data =====
                    const loyaltyTextEl = document.querySelector('.loyalty-card p');
                    if (loyaltyTextEl && data.loyalty_text) {
                        // Simply use the server-provided text which already has the correct logic
                        loyaltyTextEl.innerHTML = data.loyalty_text;
                    } else if (loyaltyTextEl) {
                        // Fallback if no data.loyalty_text
                        if (data.show_apply_button) {
                            loyaltyTextEl.innerHTML = 'Please apply for verification now if you have deposited funds, as this is required before enrollment.';
                        } else if (data.is_contract_active && data.contract_days_left > 0) {
                            loyaltyTextEl.innerHTML = `${data.contract_days_left} days left.`;
                        } else {
                            loyaltyTextEl.innerHTML = 'No active contract.';
                        }
                    }
                    
                    // Update loyalty status message
                    const loyaltiesEl = document.querySelector('.loyalty-status-msg');
                    if (loyaltiesEl && data.loyalties_message) {
                        loyaltiesEl.innerHTML = data.loyalties_message;
                    }
                    
                    // Update dashboard disclaimer
                    const disclaimerEl = document.querySelector('.dashboard-disclaimer');
                    if (disclaimerEl && data.dashboard_disclaimer) {
                        disclaimerEl.innerHTML = data.dashboard_disclaimer;
                        // Add payment badge if needed
                        if (data.loyalties_status === 'unpaid-payment') {
                            if (!disclaimerEl.querySelector('.payment-required-badge')) {
                                const badge = document.createElement('span');
                                badge.className = 'payment-required-badge';
                                badge.innerHTML = 'Payment Required';
                                disclaimerEl.appendChild(badge);
                            }
                        } else if (data.loyalties_status === 'payment-failed' || data.loyalties_status === 'failed-payment') {
                            if (!disclaimerEl.querySelector('.payment-failed-badge')) {
                                const badge = document.createElement('span');
                                badge.className = 'payment-failed-badge';
                                badge.innerHTML = '⚠ Payment Failed';
                                badge.style.cssText = 'background: #ff6b6b; color: white; padding: 2px 10px; border-radius: 12px; font-size: 11px; margin-left: 8px;';
                                disclaimerEl.appendChild(badge);
                            }
                        } else {
                            const badge = disclaimerEl.querySelector('.payment-required-badge');
                            if (badge) badge.remove();
                            const failedBadge = disclaimerEl.querySelector('.payment-failed-badge');
                            if (failedBadge) failedBadge.remove();
                        }
                    }

                    // Update loyalty button in the live updates
                    const loyaltyBtn = document.querySelector('.loyalty-card button');
                    if (loyaltyBtn && data.loyalty_btn_text) {
                        loyaltyBtn.innerHTML = data.loyalty_btn_text;
                        loyaltyBtn.className = data.loyalty_btn_class;
                        
                        // Remove any existing onclick handlers first
                        loyaltyBtn.removeAttribute('onclick');
                        loyaltyBtn.disabled = false;
                        
                        // ADD THIS: Reset button action
                        if (data.loyalty_btn_action === 'reset') {
                            loyaltyBtn.setAttribute('onclick', 'openResetModal()');
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.show_apply_button) {
                            // Apply for verification mode
                            loyaltyBtn.setAttribute('onclick', 'openApplyModal()');
                            loyaltyBtn.disabled = false;
                        } 
                        else if (data.loyalty_btn_action === 'deposit') {
                            // Deposit required mode
                            const brokerTarget = '<?= htmlspecialchars($brokerTarget) ?>';
                            loyaltyBtn.setAttribute('onclick', `window.open('${brokerTarget}', '_blank')`);
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.loyalty_btn_action === 'apply') {
                            // Apply for verification mode (fallback)
                            loyaltyBtn.setAttribute('onclick', 'openApplyModal()');
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.loyalty_btn_action === 'payment-failed') {
                            // Payment failed mode - open retry modal
                            loyaltyBtn.setAttribute('onclick', "document.getElementById('paymentFailedModal').classList.add('active')");
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.loyalties_status === 'unpaid-payment') {
                            // Profit split required mode
                            loyaltyBtn.setAttribute('onclick', "document.getElementById('profitSplitModal').classList.add('active')");
                            loyaltyBtn.disabled = false;
                        } 
                        else if (data.show_reenroll_button) {
                            // Enrollment mode
                            loyaltyBtn.setAttribute('onclick', "openReenrollModal()");
                            loyaltyBtn.disabled = false;
                        } 
                        else if (data.loyalties_status === 'payment-made') {
                            // Payment pending - disabled
                            loyaltyBtn.disabled = true;
                        } 
                        else if (data.loyalties_status === 'payment-confirmed') {
                            // Payment confirmed - ready to enroll
                            loyaltyBtn.setAttribute('onclick', "openReenrollModal()");
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.loyalties_status === 'payment-failed' || data.loyalties_status === 'failed-payment') {
                            // Payment failed - retry
                            loyaltyBtn.setAttribute('onclick', "document.getElementById('paymentFailedModal').classList.add('active')");
                            loyaltyBtn.disabled = false;
                        }
                        else if (data.is_contract_active) {
                            // Active contract - disabled
                            loyaltyBtn.disabled = true;
                        }
                        else {
                            // Default fallback - disabled
                            loyaltyBtn.disabled = true;
                        }
                    }

                    // Show/hide payment note
                    const paymentNote = document.querySelector('.loyalty-card .payment-note');
                    if (data.show_payment_note) {
                        if (!paymentNote) {
                            const note = document.createElement('p');
                            note.className = 'payment-note';
                            note.style.cssText = 'color: var(--info-color); margin-top: 10px; font-style: italic;';
                            document.querySelector('.loyalty-card').appendChild(note);
                        }
                    } else if (paymentNote) {
                        paymentNote.remove();
                    }
                    
                    // Show/hide payment failed note
                    const paymentFailedNote = document.querySelector('.loyalty-card .payment-failed-note');
                    if (data.loyalties_status === 'payment-failed' || data.loyalties_status === 'failed-payment') {
                        if (!paymentFailedNote) {
                            const note = document.createElement('p');
                            note.className = 'payment-failed-note';
                            note.style.cssText = 'color: #ff6b6b; margin-top: 10px; font-style: italic;';
                            note.innerHTML = ' ';
                            document.querySelector('.loyalty-card').appendChild(note);
                        }
                    } else if (paymentFailedNote) {
                        paymentFailedNote.remove();
                    }
                    
                    // Update profit split modal values if it exists
                    const profitModal = document.getElementById('profitSplitModal');
                    if (profitModal && data.profit_to_split) {
                        const profitAmountEl = profitModal.querySelector('.split-total');
                        if (profitAmountEl) {
                            profitAmountEl.innerHTML = `Total Profit: $${data.profit_to_split}`;
                        }
                        
                        // Update server share and user share calculations
                        const serverSharePercent = <?php echo $SERVER_SHARE_PERCENT; ?>;
                        const userSharePercent = <?php echo $USER_SHARE_PERCENT; ?>;
                        const profitAmount = parseFloat(data.profit_to_split);
                        const serverShare = (profitAmount * serverSharePercent / 100).toFixed(2);
                        const userShare = (profitAmount * userSharePercent / 100).toFixed(2);
                        
                        const serverShareEl = profitModal.querySelector('.split-item:last-child h4:last-child');
                        const userShareEl = profitModal.querySelector('.split-item:first-child h4:last-child');
                        
                        if (serverShareEl) serverShareEl.innerHTML = `$${serverShare}`;
                        if (userShareEl) userShareEl.innerHTML = `$${userShare}`;
                        
                        const paymentAmountEl = document.querySelector('#paymentModal p');
                        if (paymentAmountEl && paymentAmountEl.innerHTML.includes('Send $')) {
                            paymentAmountEl.innerHTML = `Send $${serverShare} worth of the selected cryptocurrency`;
                        }
                        
                        const hiddenAmount = document.getElementById('serverShareAmountHidden');
                        if (hiddenAmount) hiddenAmount.value = serverShare;
                    }
                    
                    // Update payment failed modal values if it exists
                    const paymentFailedModal = document.getElementById('paymentFailedModal');
                    if (paymentFailedModal && data.profit_to_split) {
                        const serverSharePercent = <?php echo $SERVER_SHARE_PERCENT; ?>;
                        const userSharePercent = <?php echo $USER_SHARE_PERCENT; ?>;
                        const profitAmount = parseFloat(data.profit_to_split);
                        const serverShare = (profitAmount * serverSharePercent / 100).toFixed(2);
                        const userShare = (profitAmount * userSharePercent / 100).toFixed(2);
                        
                        const serverShareEl = paymentFailedModal.querySelector('.split-item:last-child h4:last-child');
                        const userShareEl = paymentFailedModal.querySelector('.split-item:first-child h4:last-child');
                        
                        if (serverShareEl) serverShareEl.innerHTML = `$${serverShare}`;
                        if (userShareEl) userShareEl.innerHTML = `$${userShare}`;
                        
                        // Update the profit amount in the description
                        const profitDesc = paymentFailedModal.querySelector('p strong');
                        if (profitDesc) {
                            profitDesc.innerHTML = `$${data.profit_to_split}`;
                        }
                    }
                } else if (data.error) {
                    console.warn('Balance update error:', data.error);
                    retryCount++;
                    if (retryCount >= MAX_RETRIES) {
                        stopLiveUpdates();
                    }
                }
            } catch (error) {
                console.error('Failed to fetch live balances:', error);
                retryCount++;
                if (retryCount >= MAX_RETRIES) {
                    stopLiveUpdates();
                    const updateHint = document.createElement('div');
                    updateHint.style.cssText = 'position:fixed; bottom:10px; right:10px; background:rgba(0,0,0,0.7); color:#ff6b6b; padding:5px 10px; border-radius:5px; font-size:11px; z-index:9999;';
                    updateHint.innerText = 'Live updates paused. Refresh page to resume.';
                    document.body.appendChild(updateHint);
                    setTimeout(() => updateHint.remove(), 5000);
                }
            } finally {
                isUpdating = false;
            }
        }
        
        // Smooth number animation
        function animateValue(element, start, end, prefix = '', suffix = '', duration = 300) {
            if (!element) return;
            
            start = parseFloat(start.toString().replace(/[^0-9.-]/g, '')) || 0;
            end = parseFloat(end.toString().replace(/[^0-9.-]/g, '')) || 0;
            
            if (start === end) return;
            
            const range = end - start;
            let current = start;
            let startTime = null;
            
            function step(timestamp) {
                if (!startTime) startTime = timestamp;
                const elapsed = timestamp - startTime;
                const progress = Math.min(1, elapsed / duration);
                current = start + (range * progress);
                element.innerText = prefix + current.toFixed(2) + suffix;
                
                if (progress < 1) {
                    requestAnimationFrame(step);
                } else {
                    element.innerText = prefix + end.toFixed(2) + suffix;
                }
            }
            
            requestAnimationFrame(step);
        }
        
        // Start live updates
        function startLiveUpdates(intervalSeconds = 5) {
            if (updateInterval) {
                clearInterval(updateInterval);
            }
            
            fetchLiveBalances();
            updateInterval = setInterval(fetchLiveBalances, intervalSeconds * 1000);
        }
        
        // Stop live updates
        function stopLiveUpdates() {
            if (updateInterval) {
                clearInterval(updateInterval);
                updateInterval = null;
            }
        }
        
        // Handle page visibility
        let isPageVisible = true;
        
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                isPageVisible = false;
                if (updateInterval) {
                    clearInterval(updateInterval);
                    updateInterval = setInterval(fetchLiveBalances, 30000);
                }
            } else {
                isPageVisible = true;
                if (updateInterval) {
                    clearInterval(updateInterval);
                    updateInterval = setInterval(fetchLiveBalances, 5000);
                }
                fetchLiveBalances();
            }
        });
        
        // Initialize live updates only if not in passkey mode
        <?php if (!$show_passkey_form && $passkey_verified): ?>
        startLiveUpdates(5);
        
        window.addEventListener('beforeunload', function() {
            stopLiveUpdates();
        });
        <?php endif; ?>
</script>
<script>
    // ============== NOTIFICATION SYSTEM ==============
    
    let notificationPanelOpen = false;

    function toggleNotifications() {
        const panel = document.getElementById('notificationPanel');
        if (notificationPanelOpen) {
            panel.classList.remove('active');
            notificationPanelOpen = false;
            // Mark notifications as read when closing
            markNotificationsAsRead();
        } else {
            panel.classList.add('active');
            notificationPanelOpen = true;
            // Refresh notifications when opening
            refreshNotifications();
        }
    }

    function markNotificationsAsRead() {
        // Only mark if there are unread notifications
        const unreadItems = document.querySelectorAll('.notification-item.unread');
        if (unreadItems.length === 0) return;
        
        fetch(window.location.href, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'mark_notifications_read=1'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Update UI - remove unread class from all
                document.querySelectorAll('.notification-item.unread').forEach(item => {
                    item.classList.remove('unread');
                });
                // Hide the badge
                const badge = document.getElementById('notificationBadge');
                if (badge) {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(error => {
            console.error('Error marking notifications as read:', error);
        });
    }

    // Function to refresh notifications list
    function refreshNotifications() {
        fetch(window.location.href, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'get_notifications_list=1'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const notificationList = document.getElementById('notificationList');
                if (data.notifications && data.notifications.length > 0) {
                    let html = '';
                    data.notifications.forEach(notification => {
                        const unreadClass = notification.update === 'new' ? 'unread' : '';
                        const typeClass = notification.type || 'info';
                        
                        // Additional JavaScript sanitization
                        let cleanMessage = notification.message;
                        cleanMessage = cleanMessage.replace(/^[???]+\s*/, '');
                        cleanMessage = cleanMessage.replace(/[???]/g, '');
                        cleanMessage = cleanMessage.replace(/[\u{1F300}-\u{1F6FF}]/gu, '');
                        
                        html += `
                            <div class="notification-item ${unreadClass} ${typeClass}"
                                data-id="${notification.id}"
                                data-update="${notification.update}">
                                <div class="notification-section">${escapeHtml(notification.section)}</div>
                                <div class="notification-message">${escapeHtml(cleanMessage.trim())}</div>
                                <div class="notification-time">${formatDate(notification.time)}</div>
                            </div>
                        `;
                    });
                    notificationList.innerHTML = html;
                } else {
                    notificationList.innerHTML = '<div class="empty-notifications">No notifications</div>';
                }
                
                // Update badge count
                const badge = document.getElementById('notificationBadge');
                if (data.unread_count > 0) {
                    if (badge) {
                        badge.textContent = data.unread_count;
                        badge.style.display = 'flex';
                    } else {
                        const bell = document.querySelector('.notification-bell');
                        const newBadge = document.createElement('span');
                        newBadge.className = 'notification-badge';
                        newBadge.id = 'notificationBadge';
                        newBadge.textContent = data.unread_count;
                        bell.appendChild(newBadge);
                    }
                } else if (badge) {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(error => {
            console.error('Error refreshing notifications:', error);
        });
    }

    // Helper function to escape HTML
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }


    // Helper function to format date
    function formatDate(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins} min ago`;
        if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
        if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
        
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    // Improved polling for new notifications
    function pollNewNotifications() {
        fetch(window.location.href, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'check_new_notifications=1'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const badge = document.getElementById('notificationBadge');
                if (data.unread_count > 0) {
                    if (badge) {
                        const currentCount = parseInt(badge.textContent) || 0;
                        if (currentCount !== data.unread_count) {
                            badge.textContent = data.unread_count;
                            badge.style.display = 'flex';
                            // If panel is open, refresh the list
                            if (notificationPanelOpen) {
                                refreshNotifications();
                            }
                        }
                    } else {
                        // Create badge if it doesn't exist
                        const bell = document.querySelector('.notification-bell');
                        const newBadge = document.createElement('span');
                        newBadge.className = 'notification-badge';
                        newBadge.id = 'notificationBadge';
                        newBadge.textContent = data.unread_count;
                        bell.appendChild(newBadge);
                        // If panel is open, refresh the list
                        if (notificationPanelOpen) {
                            refreshNotifications();
                        }
                    }
                } else if (badge) {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(error => {
            console.error('Error polling notifications:', error);
        });
    }

    // Close notification panel when clicking outside
    document.addEventListener('click', function(event) {
        const panel = document.getElementById('notificationPanel');
        const bell = document.querySelector('.notification-bell');
        
        if (notificationPanelOpen && panel && !panel.contains(event.target) && !bell.contains(event.target)) {
            panel.classList.remove('active');
            notificationPanelOpen = false;
            markNotificationsAsRead();
        }
    });

    // Start polling for new notifications every 3 seconds
    setInterval(pollNewNotifications, 3000);

    // Initial refresh on page load
    document.addEventListener('DOMContentLoaded', function() {
        refreshNotifications();
    });
</script>
<script>
    // ============== REVENUE HISTORY FUNCTIONS ==============

    function openRevenueHistoryModal() {
        const modal = document.getElementById('revenueHistoryModal');
        modal.classList.add('active');
        loadRevenueHistory();
    }

    function closeRevenueHistoryModal() {
        document.getElementById('revenueHistoryModal').classList.remove('active');
    }

    function loadRevenueHistory() {
        const container = document.getElementById('revenueHistoryContainer');
        container.innerHTML = '<div class="empty-revenue">Loading...</div>';
        
        const historyData = <?php echo json_encode($user['revenue_history'] ?? '[]'); ?>;
        let history = [];
        
        if (historyData && historyData !== '[]') {
            try {
                history = typeof historyData === 'string' ? JSON.parse(historyData) : historyData;
                if (!Array.isArray(history)) history = [];
                
                // ===== CRITICAL FIX: Sort by ID descending (newest first) =====
                history.sort((a, b) => {
                    const idA = parseInt(a.id) || 0;
                    const idB = parseInt(b.id) || 0;
                    return idB - idA; // Higher ID = newer
                });
            } catch(e) {
                history = [];
            }
        }
        
        let html = '';
        
        if (history && history.length > 0) {
            // ===== CRITICAL FIX: Loop through sorted history =====
            history.forEach((record) => {
                const statusClass = getStatusClass(record.loyalties);
                const statusText = getStatusText(record.loyalties);
                const profitClass = record.profit >= 0 ? 'profit-positive' : 'profit-negative';
                const totalRevenue = record.profit < 0 ? record.profit : (record.server_share + record.user_share);
                
                const isActiveContract = (record.loyalties === 'active');
                const contractId = record.contract_id || 'N/A';
                
                let statusMessage = '';
                if (record.loyalties === 'pending_payment') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${statusText}</span>`;
                } else if (record.loyalties === 'payment-made') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${statusText} - Under Review</span>`;
                } else if (record.loyalties === 'payment-confirmed') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ✓ Payment Confirmed</span>`;
                } else if (record.loyalties === 'completed') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${statusText}</span>`;
                } else if (record.loyalties === 'loss_completed') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${statusText}</span>`;
                } else if (record.loyalties === 'below_threshold') {
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${statusText} (No Split Required)</span>`;
                } else if (record.loyalties && record.loyalties.includes('contract_cancelled')) {
                    let displayText = 'Contract Cancelled';
                    if (record.loyalties.includes('payment-confirmed')) displayText = 'Cancelled (Payment Confirmed)';
                    else if (record.loyalties.includes('payment-made')) displayText = 'Cancelled (Payment Made)';
                    else if (record.loyalties.includes('unpaid-payment')) displayText = 'Cancelled (Unpaid)';
                    else if (record.loyalties.includes('inloss')) displayText = 'Cancelled (In Loss)';
                    else if (record.loyalties.includes('below-threshold')) displayText = 'Cancelled (Below Threshold)';
                    statusMessage = `<span class="revenue-status ${statusClass}"> ${displayText}</span>`;
                } else {
                    statusMessage = `<span class="revenue-status ${statusClass}">${statusText}</span>`;
                }
                
                if (isActiveContract) {
                    const startDate = new Date(record.execution_start_date);
                    const endDate = new Date(record.execution_end_date);
                    const daysRemaining = Math.ceil((endDate - new Date()) / (1000 * 60 * 60 * 24));
                    
                    html += `
                        <div class="revenue-item active-contract-simplified" data-id="${record.id || Math.random()}">
                            <div class="revenue-header" onclick="toggleRevenueDetails(this)">
                                <div class="revenue-header-left">
                                    <div class="revenue-user-share" style="color: white; font-weight: bold; font-size: 0.9rem;">
                                        Next Revenue Harvest
                                    </div>
                                    <div class="revenue-date-range" style="color: rgb(141, 141, 141); font-weight: 600;">
                                        ${formatDateSimple(endDate)}
                                    </div>
                                </div>
                            </div>
                            <div class="revenue-details">
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Contract ID:</span>
                                    <span class="revenue-detail-value" style="font-size: 10px; font-family: monospace;">${escapeHtml(contractId)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Invested:</span>
                                    <span class="revenue-detail-value">$${formatNumber(record.starting_balance)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">⏳ Days Remaining:</span>
                                    <span class="revenue-detail-value">${daysRemaining > 0 ? daysRemaining : 0} days left</span>
                                </div>
                                <div class="revenue-detail-row" style="border-bottom: none;">
                                    <span class="revenue-detail-label">Harvest Date:</span>
                                    <span class="revenue-detail-value">${formatDateSimple(endDate)}</span>
                                </div>
                            </div>
                        </div>
                    `;
                } else {
                    html += `
                        <div class="revenue-item" data-id="${record.id || Math.random()}">
                            <div class="revenue-header" onclick="toggleRevenueDetails(this)">
                                    <div style="display: flex; align-items: stretch; width: 100%; background: transparent !important;">
                                        <div class="revenue-icon-wrapper" style="background: transparent !important;">
                                            <span class="revenue-icon" style="background: transparent !important;">💰</span>
                                        </div>
                                        <div class="revenue-header-left" style="flex: 1; display: flex; flex-direction: column; justify-content: center;">
                                            <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; flex-wrap: wrap; gap: 8px;">
                                                <div class="revenue-user-share">$${formatNumber(record.user_share)}</div>
                                            </div>
                                            <div class="revenue-date-range">${formatDateRange(record.execution_start_date, record.execution_end_date)}</div>
                                        </div>
                                    </div>
                            </div>
                            <div class="revenue-details">
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Contract ID:</span>
                                    <span class="revenue-detail-value" style="font-size: 10px; font-family: monospace;">${escapeHtml(contractId)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Invested:</span>
                                    <span class="revenue-detail-value">$${formatNumber(record.starting_balance)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Harvest (Your Share):</span>
                                    <span class="revenue-detail-value ${profitClass}">$${formatNumber(record.user_share)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Server Share:</span>
                                    <span class="revenue-detail-value">$${formatNumber(record.server_share)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Total Revenue:</span>
                                    <span class="revenue-detail-value ${profitClass}">$${formatNumber(totalRevenue)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Final Balance:</span>
                                    <span class="revenue-detail-value">$${formatNumber(record.current_balance)}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-label">Programme:</span>
                                    <span class="revenue-detail-value invested_with-value">${escapeHtml(record.invested_with || 'N/A')}</span>
                                </div>
                                <div class="revenue-detail-row">
                                    <span class="revenue-detail-value">${statusMessage}</span>
                                </div>
                            </div>
                        </div>
                    `;
                }
            });
            container.innerHTML = html;
        } else if (!html.includes('active-contract')) {
            container.innerHTML = '<div class="empty-revenue">No revenue history yet. Complete a contract to see your revenue records.</div>';
        } else {
            container.innerHTML = html;
        }
    }

    function getStatusClass(status) {
        switch(status) {
            case 'active': return 'active';
            case 'completed': return 'completed';
            case 'pending_payment': return 'pending';
            case 'loss_completed': return 'loss';
            case 'below_threshold': return 'completed';
            case 'payment-made': return 'pending';
            case 'payment-confirmed': return 'completed';
            default: return 'pending';
        }
    }

    function getStatusText(status) {
        switch(status) {
            case 'active': return 'Active Contract';
            case 'completed': return 'Completed';
            case 'pending_payment': return 'Payment Required';
            case 'loss_completed': return 'Contract ended in loss';
            case 'below_threshold': return 'Completed (Below Threshold)';
            case 'payment-made': return 'Payment Submitted';
            case 'payment-confirmed': return 'Payment Confirmed';
            default: return status || 'Recorded';
        }
    }

    function formatDateRange(startDate, endDate) {
        if (!startDate || startDate === '0000-00-00') return 'Date not set';
        
        const start = new Date(startDate);
        const end = new Date(endDate);
        
        const formatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
        return `${start.toLocaleDateString('en-US', formatOptions)} - ${end.toLocaleDateString('en-US', formatOptions)}`;
    }

    function formatNumber(value) {
        return parseFloat(value).toFixed(2);
    }
    function formatDateSimple(date) {
        if (!date) return 'Date not set';
        const d = new Date(date);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function toggleRevenueDetails(headerElement) {
        const detailsDiv = headerElement.nextElementSibling;
        const revenueItem = headerElement.closest('.revenue-item');
        
        if (detailsDiv.classList.contains('active')) {
            detailsDiv.classList.remove('active');
            if (revenueItem) {
                revenueItem.style.width = '100%';
            }
        } else {
            document.querySelectorAll('.revenue-details.active').forEach(detail => {
                detail.classList.remove('active');
            });
            
            document.querySelectorAll('.revenue-item').forEach(item => {
                item.style.width = '100%';
            });
            
            detailsDiv.classList.add('active');
            
            if (revenueItem) {
                const originalWidth = revenueItem.offsetWidth;
                revenueItem.style.width = originalWidth + 'px';
                setTimeout(() => {
                    revenueItem.style.width = '100%';
                }, 10);
            }
        }
    }

    // Close modal when clicking outside
    document.addEventListener('click', function(event) {
        const modal = document.getElementById('revenueHistoryModal');
        if (event.target === modal) {
            closeRevenueHistoryModal();
        }
    });
    // --- INACTIVITY RELOAD (1 MINUTE) - RELOADS EVERY TIME (ONLY IF PASSKEY MODAL NOT ACTIVE) ---
    let inactivityTimer;
    const INACTIVITY_LIMIT = 60 * 1000; // 1 minute in milliseconds

    function resetInactivityTimer() {
        clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => {
            // Check if passkey modal is active before reloading
            const passkeyOverlay = document.getElementById('reenrollPasskeyOverlay');
            const passkeyScreen = document.querySelector('.passkey-overlay');
            const passkeyForm = document.querySelector('.passkey-screen');
            
            // Check if ANY passkey-related modal is visible/active
            let isPasskeyModalActive = false;
            
            // Check for enrollment passkey overlay
            if (passkeyOverlay && passkeyOverlay.classList.contains('active')) {
                isPasskeyModalActive = true;
                console.log('Inactivity reload skipped: Passkey verification overlay is active');
            }
            
            // Check for main passkey overlay (create passkey or enter passkey)
            if (passkeyScreen && passkeyScreen.offsetParent !== null) {
                // offsetParent is null if element is hidden/display:none
                isPasskeyModalActive = true;
                console.log('Inactivity reload skipped: Passkey screen is visible');
            }
            
            // Check if passkey form is visible (fallback check)
            if (passkeyForm && window.getComputedStyle(passkeyForm).display !== 'none') {
                isPasskeyModalActive = true;
                console.log('Inactivity reload skipped: Passkey form is visible');
            }
            
            // Also check if any modal with 'passkey' in its ID or class is active
            const allModals = document.querySelectorAll('.modal.active, .passkey-overlay, .passkey-verification-overlay');
            allModals.forEach(modal => {
                if (modal.id && (modal.id.includes('passkey') || modal.id.includes('Passkey'))) {
                    if (modal.classList.contains('active') || (modal.offsetParent !== null)) {
                        isPasskeyModalActive = true;
                        console.log('Inactivity reload skipped: Passkey modal "' + modal.id + '" is active');
                    }
                }
                if (modal.classList && modal.classList.contains('passkey-verification-overlay') && modal.classList.contains('active')) {
                    isPasskeyModalActive = true;
                    console.log('Inactivity reload skipped: Passkey verification overlay is active');
                }
            });
            
            // Only reload if NO passkey modal is active
            if (!isPasskeyModalActive) {
                console.log('Inactivity reload triggered: No passkey modal active, reloading page...');
                window.location.reload();
            } else {
                console.log('Inactivity reload skipped: Passkey modal is active');
                // Reset timer to check again later (since passkey might be dismissed)
                resetInactivityTimer();
            }
        }, INACTIVITY_LIMIT);
    }

    // Reset timer on user activity
    window.addEventListener('load', resetInactivityTimer);
    window.addEventListener('mousemove', resetInactivityTimer);
    window.addEventListener('mousedown', resetInactivityTimer);
    window.addEventListener('keypress', resetInactivityTimer);
    window.addEventListener('scroll', resetInactivityTimer);
    window.addEventListener('touchstart', resetInactivityTimer);
    window.addEventListener('click', resetInactivityTimer);

    // Also reset timer when modals are closed (to prevent immediate reload after closing passkey)
    const originalCloseModalFunctions = {
        closeReenrollPasskeyOverlay: window.closeReenrollPasskeyOverlay,
        closeApplyModal: window.closeApplyModal
    };

    // Enhance closeReenrollPasskeyOverlay to reset timer
    window.closeReenrollPasskeyOverlay = function() {
        if (originalCloseModalFunctions.closeReenrollPasskeyOverlay) {
            originalCloseModalFunctions.closeReenrollPasskeyOverlay();
        }
        resetInactivityTimer();
    };

    // Enhance closeApplyModal to reset timer
    window.closeApplyModal = function() {
        if (originalCloseModalFunctions.closeApplyModal) {
            originalCloseModalFunctions.closeApplyModal();
        }
        resetInactivityTimer();
    };
    // ============== APPLY SUCCESS MODAL FUNCTIONS ==============

    function openApplySuccessModal(message, details) {
        const modal = document.getElementById('applySuccessModal');
        const msgEl = document.getElementById('applySuccessMessage');
        const detailsEl = document.getElementById('applySuccessDetails');
        
        if (msgEl) msgEl.textContent = message || 'Your application has been submitted successfully!';
        if (detailsEl) detailsEl.textContent = details || 'Our team will verify your account. Please ensure you have deposited the minimum required amount.';
        
        if (modal) {
            modal.classList.add('active');
            // Auto-close after 6 seconds
            setTimeout(function() {
                closeApplySuccessModal();
            }, 6000);
        }
    }

    function closeApplySuccessModal() {
        const modal = document.getElementById('applySuccessModal');
        if (modal) {
            modal.classList.remove('active');
        }
    }

    // Close apply success modal when clicking outside
    document.addEventListener('click', function(event) {
        const modal = document.getElementById('applySuccessModal');
        if (event.target === modal) {
            closeApplySuccessModal();
        }
    });

    // Also reset timer when any modal is closed
    document.addEventListener('click', function(event) {
        const modals = document.querySelectorAll('.modal.active, .passkey-overlay.active, .passkey-verification-overlay.active');
        if (modals.length > 0 && event.target.classList && event.target.classList.contains('modal')) {
            // Modal is being closed
            resetInactivityTimer();
        }
    });
    // Prevent overscroll page reload
    document.addEventListener('touchmove', function(e) {
        const element = e.target;
        let scrollable = false;
        let current = element;
        
        // Check if the target element is scrollable
        while (current && current !== document.body) {
            const overflowY = window.getComputedStyle(current).overflowY;
            if (overflowY === 'auto' || overflowY === 'scroll') {
                scrollable = true;
                break;
            }
            current = current.parentElement;
        }
        
        if (!scrollable) {
            const scrollTop = document.documentElement.scrollTop || document.body.scrollTop;
            const scrollHeight = document.documentElement.scrollHeight;
            const clientHeight = document.documentElement.clientHeight;
            
            // Prevent pull-to-refresh at top or bottom
            if ((scrollTop === 0 && e.touches[0].clientY > e.touches[0].clientY) ||
                (scrollTop + clientHeight >= scrollHeight && e.touches[0].clientY < e.touches[0].clientY)) {
                e.preventDefault();
            }
        }
    }, { passive: false });
        // ============== RESET CONTRACT FUNCTIONS ==============
    
    function openResetModal() {
        const modal = document.getElementById('resetModal');
        if (modal) {
            modal.classList.add('active');
        }
    }
    
    function closeResetModal() {
        const modal = document.getElementById('resetModal');
        if (modal) {
            modal.classList.remove('active');
        }
    }
</script>
</body>
</html>

