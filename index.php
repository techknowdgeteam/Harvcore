<?php
    session_start();
    //index.php
    // ==================== DATABASE CONNECTION ====================
    try {
        $pdo = new PDO(
            "mysql:host=sql312.infinityfree.com;dbname=if0_40473107_harvhub;charset=utf8mb4",
            "if0_40473107",
            "InDQmdl53FZ85",
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );
    } catch (Exception $e) {
        die("Database connection failed.");
    }

    // ==================== FETCH SERVER ACCOUNT SETTINGS ====================
    $min_broker_balance = 50.00;
    try {
        $stmt = $pdo->query("SELECT min_broker_balance FROM server_account LIMIT 1");
        $serverConfig = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($serverConfig && isset($serverConfig['min_broker_balance'])) {
            $min_broker_balance = (float)$serverConfig['min_broker_balance'];
        }
    } catch (PDOException $e) {}

    // ==================== FETCH BROKER CONFIGURATION ====================
    $allowed_brokers = [];
    $broker_targets = [];
    $error = '';

    try {
        $stmt = $pdo->query("SELECT brokers, brokers_link FROM server_account LIMIT 1");
        $config = $stmt->fetch(PDO::FETCH_ASSOC);

        if ($config) {
            $raw_brokers = explode(',', $config['brokers'] ?? '');
            foreach ($raw_brokers as $entry) {
                if (preg_match('/(insiders):\s*(.+)/i', trim($entry), $matches)) {
                    $broker_name = trim($matches[2]);
                    if (!in_array(ucfirst($broker_name), $allowed_brokers)) {
                        $allowed_brokers[] = ucfirst($broker_name);
                    }
                }
            }

            $raw_links = explode(',', $config['brokers_link'] ?? '');
            foreach ($raw_links as $entry) {
                if (preg_match('/(insiders):\s*(.+)/i', trim($entry), $matches)) {
                    $broker_key = trim($matches[2]);
                    $broker_link_parts = explode(':', $broker_key, 2);
                    if (count($broker_link_parts) == 2) {
                        $link_name = trim($broker_link_parts[0]);
                        $link_url = trim($broker_link_parts[1]);
                        $target_url = (strpos($link_url, '://') === false && !empty($link_url)) ? 'https://' . $link_url : $link_url;
                        $broker_targets[ucfirst($link_name)] = $target_url;
                    } elseif (!empty($broker_key)) {
                        $key_parts = explode('.', $broker_key);
                        $link_name = ucfirst($key_parts[0]);
                        $target_url = (strpos($broker_key, '://') === false && !empty($broker_key)) ? 'https://' . $broker_key : $broker_key;
                        $broker_targets[$link_name] = $target_url;
                    }
                }
            }
        }
        $allowed_brokers = array_unique($allowed_brokers);
        sort($allowed_brokers);
    } catch (PDOException $e) {
        $error = "Failed to load broker configuration.";
    }

    $just_submitted = $_SESSION['just_submitted'] ?? false;
    unset($_SESSION['just_submitted']); 
    
    if (isset($_GET['logout'])) {
        session_unset();
        session_destroy();
        header("Location: index.php");
        exit;
    }
    
    $logged_in_email = $_SESSION['user_email'] ?? '';
    $already_submitted = false;
    $application_status = '';
    $user_broker = '';
    $user_server = '';
    $user_login = '';
    $user_fullname = '';
    $user_broker_balance = 0;
    $user_profitandloss = 0;
    $login_error = '';
    $login_success = false;

    // ==================== CHECK USER STATUS (EMAIL VERIFICATION FIRST - GRANDPARENT) ====================
    if ($logged_in_email !== '') {
        $stmt = $pdo->prepare("SELECT email_verified, application_status FROM insiders WHERE email = ? LIMIT 1");
        $stmt->execute([strtolower($logged_in_email)]);
        $user_check = $stmt->fetch(PDO::FETCH_ASSOC);
        
        if ($user_check) {
            // STEP 1: ALWAYS CHECK EMAIL VERIFICATION FIRST - THIS IS THE GRANDPARENT CHECK
            // NO ONE bypasses this - not even approved users!
            if (isset($user_check['email_verified']) && $user_check['email_verified'] == 0) {
                // Determine where to return after verification
                $return_to = 'index.php';
                
                // If user is approved, send them back to dashboard after verification
                if (strtolower($user_check['application_status'] ?? '') === 'approved') {
                    $return_to = 'mydashboard.php';
                }
                
                // Store the email and return location for verification
                $_SESSION['pending_verification_email'] = $logged_in_email;
                $_SESSION['otp_step'] = 'request';
                $_SESSION['return_after_verify'] = $return_to;
                $_SESSION['is_approved_user'] = (strtolower($user_check['application_status'] ?? '') === 'approved') ? true : false;
                
                // Redirect to verify_email.php - THIS TAKES PRIORITY OVER EVERYTHING!
                header("Location: verify_email.php");
                exit;
            }
            
            // STEP 2: ONLY AFTER EMAIL IS VERIFIED, check if user is approved
            if (strtolower($user_check['application_status'] ?? '') === 'approved') {
                header("Location: mydashboard.php");
                exit;
            }
        }
    }

    // ==================== HANDLE LOGIN / SIGNUP ====================
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['login_email'])) {
        $email = trim(strtolower($_POST['login_email']));
        
        if (filter_var($email, FILTER_VALIDATE_EMAIL)) {
            // Check if user exists
            $stmt = $pdo->prepare("SELECT id, passkey, application_status, email_verified FROM insiders WHERE email = ? LIMIT 1");
            $stmt->execute([$email]);
            $user = $stmt->fetch(PDO::FETCH_ASSOC);
            
            if ($user) {
                // STEP 1: ALWAYS CHECK EMAIL VERIFICATION FIRST - GRANDPARENT CHECK
                if (isset($user['email_verified']) && $user['email_verified'] == 0) {
                    // Email not verified - redirect to verify_email.php
                    $_SESSION['pending_verification_email'] = $email;
                    $_SESSION['otp_step'] = 'request';
                    $_SESSION['return_after_verify'] = 'index.php';
                    $_SESSION['is_approved_user'] = (strtolower($user['application_status'] ?? '') === 'approved') ? true : false;
                    
                    // If user is approved, send them back to dashboard after verification
                    if (strtolower($user['application_status'] ?? '') === 'approved') {
                        $_SESSION['return_after_verify'] = 'mydashboard.php';
                    }
                    
                    // Store email in session so they don't need to re-enter
                    $_SESSION['user_email'] = $email;
                    
                    header("Location: verify_email.php");
                    exit;
                }
                
                // STEP 2: ONLY AFTER EMAIL IS VERIFIED, check passkey and status
                
                // Check if user is approved - redirect directly to dashboard
                if (strtolower($user['application_status'] ?? '') === 'approved') {
                    // Email is verified, passkey check will happen below
                    // Let's check passkey first
                    if (isset($_POST['passkey']) && !empty($_POST['passkey'])) {
                        if (password_verify($_POST['passkey'], $user['passkey'] ?? '')) {
                            $_SESSION['user_email'] = $email;
                            $login_success = true;
                            header("Location: mydashboard.php");
                            exit;
                        } else {
                            $login_error = "Incorrect passkey. Please try again.";
                            $_SESSION['login_email_temp'] = $email;
                            $_SESSION['login_error'] = $login_error;
                            header("Location: index.php");
                            exit;
                        }
                    } else {
                        // Approved user but no passkey provided - show passkey field
                        $_SESSION['login_email_temp'] = $email;
                        $_SESSION['show_passkey_field'] = true;
                        header("Location: index.php");
                        exit;
                    }
                }
                
                // User exists but NOT approved - check passkey
                if (isset($_POST['passkey']) && !empty($_POST['passkey'])) {
                    if (password_verify($_POST['passkey'], $user['passkey'] ?? '')) {
                        $_SESSION['user_email'] = $email;
                        $login_success = true;
                        header("Location: index.php");
                        exit;
                    } else {
                        $login_error = "Incorrect passkey. Please try again.";
                        $_SESSION['login_email_temp'] = $email;
                        $_SESSION['login_error'] = $login_error;
                        header("Location: index.php");
                        exit;
                    }
                } else {
                    // Passkey not provided - store email and show passkey field
                    $_SESSION['login_email_temp'] = $email;
                    $_SESSION['show_passkey_field'] = true;
                    header("Location: index.php");
                    exit;
                }
            } else {
                // User doesn't exist - show signup modal
                $_SESSION['signup_email'] = $email;
                $_SESSION['show_signup_modal'] = true;
                header("Location: index.php");
                exit;
            }
        } else {
            $login_error = "Invalid email address.";
            $_SESSION['login_error'] = $login_error;
            header("Location: index.php");
            exit;
        }
    }
    // ==================== HANDLE SIGNUP ====================
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['signup_submit'])) {
        $email = trim(strtolower($_POST['signup_email']));
        $fullname = trim($_POST['signup_fullname'] ?? '');
        $passkey = $_POST['signup_passkey'] ?? '';
        $confirm_passkey = $_POST['signup_confirm_passkey'] ?? '';
        $signup_error = '';
        
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            $signup_error = "Invalid email address.";
        } elseif (empty($fullname)) {
            $signup_error = "Please enter your full name.";
        } elseif (empty($passkey) || strlen($passkey) < 4) {
            $signup_error = "Passkey must be at least 4 characters long.";
        } elseif ($passkey !== $confirm_passkey) {
            $signup_error = "Passkeys do not match.";
        } else {
            // Check if user already exists and is verified
            $stmt = $pdo->prepare("SELECT id, email_verified FROM insiders WHERE email = ? LIMIT 1");
            $stmt->execute([$email]);
            $existing = $stmt->fetch();
            
            if ($existing && $existing['email_verified'] == 1) {
                $signup_error = "This email is already verified. Please login instead.";
            } else {
                // DON'T CREATE USER YET - just store in session for verification
                $hashed_passkey = password_hash($passkey, PASSWORD_DEFAULT);
                
                // Store credentials in session (not database)
                $_SESSION['pending_verification_email'] = $email;
                $_SESSION['pending_verification_fullname'] = $fullname; // Store fullname
                $_SESSION['pending_verification_passkey'] = $hashed_passkey;
                $_SESSION['otp_step'] = 'request';
                $_SESSION['return_after_verify'] = 'index.php';
                $_SESSION['signup_in_progress'] = true;
                
                // Redirect to OTP verification
                header("Location: verify_email.php");
                exit;
            }
        }
        
        if (!empty($signup_error)) {
            $_SESSION['signup_error'] = $signup_error;
            $_SESSION['signup_email'] = $email;
            $_SESSION['signup_fullname'] = $fullname; // Store for re-population
            $_SESSION['show_signup_modal'] = true;
            header("Location: index.php");
            exit;
        }
    }

    // Clear session flags after handling
    $show_passkey_field = $_SESSION['show_passkey_field'] ?? false;
    $login_email_temp = $_SESSION['login_email_temp'] ?? '';
    $login_error = $_SESSION['login_error'] ?? '';
    $show_signup_modal = $_SESSION['show_signup_modal'] ?? false;
    $signup_email = $_SESSION['signup_email'] ?? '';
    $signup_error = $_SESSION['signup_error'] ?? '';
    
    // Clear after reading
    unset($_SESSION['show_passkey_field']);
    unset($_SESSION['login_email_temp']);
    unset($_SESSION['login_error']);
    unset($_SESSION['show_signup_modal']);
    unset($_SESSION['signup_email']);
    unset($_SESSION['signup_error']);

    // ==================== FETCH USER DATA ====================
    if ($logged_in_email !== '') {
        $stmt = $pdo->prepare("SELECT application_status, broker, server, login, fullname, broker_balance, profitandloss FROM insiders WHERE email = ? LIMIT 1");
        $stmt->execute([strtolower($logged_in_email)]);
        
        if ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
            $application_status = $row['application_status'] ?? '';
            $user_broker = $row['broker'] ?? '';
            $user_server = $row['server'] ?? '';
            $user_login = $row['login'] ?? '';
            $user_fullname = $row['fullname'] ?? ''; // KEEP THIS
            $user_broker_balance = (float)($row['broker_balance'] ?? 0);
            $user_profitandloss = (float)($row['profitandloss'] ?? 0);

            if (!empty($application_status)) {
                $already_submitted = true;
            } else {
                $already_submitted = false;
            }
        }
    }
    
    // ==================== EDIT BROKER DETAILS ====================
    if (empty($error) && $_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['edit_insider']) && $logged_in_email !== '' && $application_status === 'pending') {
        $broker = $_POST['broker'] ?? '';
        $server = trim($_POST['server'] ?? '');
        $login = trim($_POST['login'] ?? ''); 
        $password = $_POST['password'] ?? '';
        
        if (!in_array($broker, $allowed_brokers)) { 
            $error = "Invalid broker selected.";
        } elseif (empty($server) || empty($login) || empty($password)) {
            $error = "All fields are required.";
        } else {
            try {
                $stmt = $pdo->prepare("
                    SELECT email, application_status 
                    FROM insiders 
                    WHERE login = ? AND server = ? AND email != ?
                    LIMIT 1
                ");
                $stmt->execute([$login, $server, strtolower($logged_in_email)]);
                $existing_account = $stmt->fetch();

                if ($existing_account) {
                    $error = "This broker account (Login No. and Server) is already registered by another user.";
                }
            } catch (PDOException $e) {
                $error = "Database check failed. Please try again.";
            }
        }
        
        if (empty($error)) {
            try {
                $stmt = $pdo->prepare("
                    UPDATE insiders 
                    SET broker = ?, server = ?, login = ?, password = ?, application_status = 'pending'
                    WHERE email = ?
                ");
                $stmt->execute([$broker, $server, $login, $password, strtolower($logged_in_email)]);
                
                $_SESSION['just_submitted'] = true;
                header("Location: index.php");
                exit;
            } catch (PDOException $e) {
                $error = "Update failed. Try again.";
            }
        }
    }
    
    // ==================== SUBMIT BROKER DETAILS ====================
    if (empty($error) && $_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['submit_insider']) && $logged_in_email !== '') {
        $broker = $_POST['broker'] ?? '';
        $server = trim($_POST['server'] ?? '');
        $login = trim($_POST['login'] ?? ''); 
        $password = $_POST['password'] ?? '';
        
        if (!in_array($broker, $allowed_brokers)) { 
            $error = "Invalid broker selected.";
        } elseif (empty($server) || empty($login) || empty($password)) {
            $error = "All fields are required.";
        } else {
            try {
                $stmt = $pdo->prepare("
                    SELECT email, application_status 
                    FROM insiders 
                    WHERE login = ? AND server = ? 
                    LIMIT 1
                ");
                $stmt->execute([$login, $server]);
                $existing_account = $stmt->fetch();

                if ($existing_account) {
                    if ($existing_account['email'] !== strtolower($logged_in_email)) {
                        $error = "This broker account (Login No. and Server) is already registered by another user.";
                    } elseif ($existing_account['application_status'] === 'blacklisted') {
                        $error = "Your submission is not allowed. This account is blacklisted.";
                    }
                }
            } catch (PDOException $e) {
                $error = "Database check failed. Please try again.";
            }
        }
        
        if (empty($error)) {
            try {
                $stmt = $pdo->prepare("
                    UPDATE insiders 
                    SET broker = ?, server = ?, login = ?, password = ?, application_status = 'pending'
                    WHERE email = ?
                ");
                $stmt->execute([$broker, $server, $login, $password, strtolower($logged_in_email)]);
                
                $_SESSION['just_submitted'] = true;
                header("Location: index.php");
                exit;
            } catch (PDOException $e) {
                $error = "Submission failed. Try again.";
            }
        }
    }

    // ==================== AJAX HANDLER FOR LIVE UPDATES ====================
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_SERVER['HTTP_X_REQUESTED_WITH']) && 
        strtolower($_SERVER['HTTP_X_REQUESTED_WITH']) === 'xmlhttprequest') {
        header('Content-Type: application/json');
        
        $action = $_POST['action'] ?? '';
        
        if ($action === 'get_user_status' && isset($_POST['email'])) {
            $email = strtolower(trim($_POST['email']));
            
            try {
                $stmt = $pdo->prepare("SELECT application_status, broker, server, login, fullname, broker_balance, profitandloss FROM insiders WHERE email = ? LIMIT 1");
                $stmt->execute([$email]);
                $user = $stmt->fetch(PDO::FETCH_ASSOC);
                
                if ($user) {
                    $brokerBalance = (float)($user['broker_balance'] ?? 0);
                    $profitAndLoss = (float)($user['profitandloss'] ?? 0);
                    $currentBalance = $brokerBalance + $profitAndLoss;
                    
                    echo json_encode([
                        'success' => true,
                        'application_status' => $user['application_status'] ?: 'Not Submitted',
                        'broker_balance' => $brokerBalance,
                        'profitandloss' => $profitAndLoss,
                        'current_balance' => $currentBalance,
                        'broker' => $user['broker'] ?? '',
                        'server' => $user['server'] ?? '',
                        'login' => $user['login'] ?? '',
                        'fullname' => $user['fullname'] ?? ''
                    ]);
                } else {
                    echo json_encode([
                        'success' => true,
                        'application_status' => 'Not Submitted'
                    ]);
                }
            } catch (PDOException $e) {
                echo json_encode(['success' => false, 'error' => 'Database error']);
            }
            exit;
        }
        
        echo json_encode(['success' => false, 'error' => 'Invalid action']);
        exit;
    }
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HarvHub</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<?php include 'index_style.php' ?>

</head>
<body class="<?php echo ($logged_in_email !== '') ? 'logged-in' : ''; ?>">
    <div class="custom-body">
        <div class="container">
            <header>
                <?php if ($logged_in_email !== '' && $already_submitted && $application_status !== 'approved'): ?>
                    <div class="user-profile-status">
                        <div id="profileIcon">👤</div> 
                        <div id="profileCard" class="profile-details">
                            <div class="profile-header">
                                <p style="font-weight:bold; color:var(--accent); font-size:1.1rem; margin-bottom:8px;">Profile Broker Details</p>
                                <?php if ($application_status === 'pending' && !empty($user_broker)): ?>
                                    <button class="edit-btn" onclick="openEditModal()">Edit</button>
                                <?php endif; ?>
                            </div>
                            <?php if (!empty($user_broker)): ?>
                                <p><strong>Broker:</strong> <?= htmlspecialchars($user_broker) ?></p>
                                <p><strong>Login:</strong> <?= htmlspecialchars($user_login) ?></p>
                                <p><strong>Server:</strong> <?= htmlspecialchars($user_server) ?></p>
                            <?php endif; ?>
                            <div id="liveBrokerData" style="font-size:0.85rem; margin-top:8px;"></div>
                        </div>
                    </div>
                <?php endif; ?>
                
                <div>
                <h1>HarvHub</h1>
                </div>
                
                <?php if ($logged_in_email !== '' && !empty($user_fullname) && $already_submitted && $application_status !== 'approved'): ?>
                    <div class="welcome-message">
                        Welcome, <strong><?= htmlspecialchars($user_fullname) ?></strong>
                    </div>
                <?php endif; ?>
                

                <?php if ($logged_in_email !== '' && $already_submitted && $application_status !== 'approved'): ?>
                    <div id="mobileProfileStatus" class="profile-details">
                        <div class="profile-header">
                            <p style="font-weight:bold; color:var(--accent); font-size:1.1rem; margin-bottom:8px;">Your Broker</p>
                            <?php if ($application_status === 'pending' && !empty($user_broker)): ?>
                                <button class="edit-btn" onclick="openEditModal()"> Edit</button>
                            <?php endif; ?>
                        </div>
                        <?php if (!empty($user_broker)): ?>
                            <p><strong>Broker:</strong> <?= htmlspecialchars($user_broker) ?></p>
                            <p><strong>Login:</strong> <?= htmlspecialchars($user_login) ?></p>
                            <p><strong>Server:</strong> <?= htmlspecialchars($user_server) ?></p>
                        <?php endif; ?>
                        <div id="mobileLiveData" style="font-size:0.85rem; margin-top:8px;"></div>
                    </div>
                <?php endif; ?>
            </header>
            
            <!-- Organized Information Grid - Only show if user is NOT approved -->
            <?php if ($application_status !== 'approved'): ?>
            <div class="info-grid">
                <?php if (!$logged_in_email || ($logged_in_email && $already_submitted)): ?>
                <div class="info-card">
                    <h3>Investing & Harvesting</h3>
                    <ul>
                        <li>Deposit to your broker MT5.</li>
                        <li>Apply for account verification after approval.</li>
                        <li>Enroll to start the programme.</li>
                        <li>Market conditions determine the results and returns.</li>
                        <li>Trades are fully automated during the contract period.</li>
                        <li>Harvest your profits after contract period.</li>
                        <li>Our service prioritizes the safety of your capital, though we cannot fully control market results.</li>
                    </ul>
                </div>
                
                <div class="info-card" style="display: none">
                    <h3>For Developers</h3>
                    <p>Build and submit your trading strategies for automated analysis on your chosen markets. Your developed strategy must have at least a 40% win rate.</p>
                    <ul>
                        <li>Submit technical analysis via the Developer Dashboard for review.</li>
                        <li>Automated strategy validation.</li>
                        <li>Live market execution.</li>
                    </ul>
                </div>
                
                <div class="info-card" style="display: none">
                    <h3>For Account Managers</h3>
                    <p>Build your own strategies if you are a developer, or purchase proven strategies from other developers to attract investors and grow your portfolio.</p>
                    <ul>
                        <li>A minimum 40% win rate is required for the strategy.</li>
                        <li>Set your own profit percentage and conditions.</li>
                        <li>You must deposit funds and link your live account to your strategy to trade alongside your investors, ensuring transparency.</li>
                    </ul>
                </div>
                
                <div class="info-card">
                    <h3>Requirements & Guidelines</h3>
                    <ul>
                        <li>Investor: Ensure minimum of <strong>$<?= number_format($min_broker_balance, 2) ?></strong> is deposited into your broker account.</li>
                        <li>Real Account: Only real accounts will be verified; demo accounts are not allowed.</li>
                        <li>Profit Split: After contract completion, ensure you send the server percentage to remain eligible for the programme.</li>
                        <li>Rules & Regulations: Do not withdraw profits, place trades, modify trades, transfer or deposit funds into your MT5 during the contract period.</li>
                    </ul>
                </div>
                <?php else: ?>
                <!-- ONLY show Complete Registration card when logged in but not submitted -->
                <div class="info-card" style="border: 2px solid var(--accent); width: 100%; max-width: 600px; margin: 0 auto;">
                    <p style="font-size: 1.1rem; margin: 15px 0; text-align: center;">
                        <strong>Complete registration now to proceed</strong>
                    </p>
                    <ul style="text-align: center; list-style: none; padding: 0;">
                        <li style="margin: 10px 0;">You need to complete your registration to access the full programme.</li>
                    </ul>
                </div>
                <?php endif; ?>
            </div>
            <?php endif; ?>
            
            <div style="text-align:center; margin:2rem 0;">
                <?php
                $button_text = 'Complete registration';
                $button_id = 'joinBtn';
                $button_onclick = '';
                $button_class = 'btn';

                if ($logged_in_email === '') {
                    $button_text = 'Sign up or Login';
                } elseif ($already_submitted) {
                    $status_lower = strtolower($application_status);
                    if ($status_lower === 'blacklisted') {
                        $button_text = 'You will be invited';
                        $button_id = 'blacklistedBtn';
                        $button_class = 'btn blacklisted'; 
                        $button_onclick = ''; 
                    } elseif ($status_lower === 'approved') {
                        $button_text = 'Go to Dashboard';
                        $button_id = 'dashboardBtn';
                        $button_onclick = "window.location.href='mydashboard.php'";
                    } elseif ($status_lower === 'declined') {
                        $button_text = 'Not Eligible';
                        $button_id = 'declinedBtn';
                    } else {
                        $button_text = 'Application Received';
                        $button_id = 'submittedBtn';
                    }
                }
                ?>
                <div style="margin-bottom: 60px;">
                    <button class="<?= $button_class ?>" id="<?= $button_id ?>" <?= $button_onclick ? "onclick=\"$button_onclick\"" : "" ?>>
                        <?= $button_text ?>
                    </button>
                    <?php if ($logged_in_email !== ''): ?>
                        <div class="central-logout">
                            <a href="?logout=1">Logout</a>
                        </div>
                    <?php endif; ?>
                </div>
            </div>
        </div>
        
        <!-- Modal sections -->
        <!-- Email/Login Modal -->
        <div id="emailModal" class="modal <?php echo ($show_passkey_field || $login_error) ? 'active' : ''; ?>">
            <div class="modal-content">
                <span class="close" onclick="closeModal('emailModal')">×</span>
                <h2 style="text-align:center;">Login to your account</h2>
                <form method="POST" style="margin-top:30px;" id="loginForm">
                    <input type="email" name="login_email" id="loginEmailInput" placeholder="Enter your email" required style="text-align:center; font-size:1.1rem;" value="<?= htmlspecialchars($login_email_temp) ?>">
                    
                    <?php if ($show_passkey_field || $login_error): ?>
                        <div id="passkeyFieldContainer" style="margin-top: 15px;">
                            <input type="password" name="passkey" id="loginPasskeyInput" placeholder="Enter your passkey" required style="text-align:center; font-size:1.1rem;">
                            <?php if ($login_error): ?>
                                <p class="error-text" style="color: #ff6b6b; margin-top: 8px;"><?= htmlspecialchars($login_error) ?></p>
                            <?php endif; ?>
                        </div>
                        <button type="submit" class="btn" style="width:100%; margin-top:15px;">Login</button>
                        <p style="margin-top: 15px; text-align: center; font-size: 0.9rem; opacity: 0.7;">
                            <a href="forgot_passkey.php" style="color: var(--accent);">Forgot Passkey?</a>
                        </p>
                    <?php else: ?>
                        <button type="submit" class="btn" style="width:100%; margin-top:15px;">Continue</button>
                    <?php endif; ?>
                    
                    <!-- ===== NEW: Create Account Button ===== -->
                    <div style="margin-top: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;">
                        <button type="button" class="btn" style="width:100%; background: transparent; border: 2px solid var(--accent); color: var(--accent);" onclick="closeModal('emailModal'); openSignupModal();">
                            Create an Account
                        </button>
                    </div>
                    <!-- ===== END NEW ===== -->
                </form>
            </div>
        </div>
        
        <!-- Signup Modal (shown when email doesn't exist) -->
        <div id="signupModal" class="modal <?php echo $show_signup_modal ? 'active' : ''; ?>">
            <div class="modal-content">
                <span class="close" onclick="closeModal('signupModal')">×</span>
                <h2 style="text-align:center;">Create Your Account</h2>
                <p style="text-align:center; opacity:0.7; margin-bottom: 20px;">The email you entered is not registered. Create a new account below.</p>
                <form method="POST" style="margin-top:10px;">
                    <input type="hidden" name="signup_submit" value="1">
                    
                    <label style="display:block; margin-bottom: 5px; font-weight:600;">Full Name</label>
                    <input type="text" name="signup_fullname" placeholder="Enter your full name" required style="text-align:center; font-size:1.1rem;" value="<?= htmlspecialchars($_SESSION['signup_fullname'] ?? '') ?>">
                    
                    <label style="display:block; margin-top: 15px; margin-bottom: 5px; font-weight:600;">Email Address</label>
                    <input type="email" name="signup_email" placeholder="youremail@gmail.com" required style="text-align:center; font-size:1.1rem;" value="<?= htmlspecialchars($signup_email) ?>">
                    
                    <label style="display:block; margin-top: 15px; margin-bottom: 5px; font-weight:600;">Set Passkey</label>
                    <input type="password" name="signup_passkey" id="signupPasskey" placeholder="Create a strong passkey (min 4 characters)" required style="text-align:center; font-size:1.1rem;">
                    
                    <label style="display:block; margin-top: 10px; margin-bottom: 5px; font-weight:600;">Confirm Passkey</label>
                    <input type="password" name="signup_confirm_passkey" id="signupConfirmPasskey" placeholder="Confirm your passkey" required style="text-align:center; font-size:1.1rem;">
                    
                    <?php if ($signup_error): ?>
                        <p class="error-text" style="color: #ff6b6b; margin-top: 12px;"><?= htmlspecialchars($signup_error) ?></p>
                    <?php endif; ?>
                    
                    <button type="submit" class="btn" style="width:100%; margin-top:20px;">Create Account</button>
                    <p style="margin-top: 15px; text-align: center; font-size: 0.9rem; opacity: 0.7;">
                        Already have an account? <a href="#" onclick="closeModal('signupModal'); openEmailModal(); return false;" style="color: var(--accent);">Login</a>
                    </p>
                </form>
            </div>
        </div>
        
        <div id="brokerModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeModal('brokerModal')">×</span>
                <h2 style="text-align:center;">Register with a Broker</h2>
                <div style="text-align:center; margin:2rem 0;">
                    <?php if (!empty($allowed_brokers)): ?>
                        <?php foreach ($allowed_brokers as $broker): 
                            $link_url = $broker_targets[$broker] ?? 'about:blank';
                        ?>
                            <a href="<?= htmlspecialchars($link_url) ?>" target="_blank" class="btn" style="width:80%; max-width:350px; margin:10px auto; display:block;">
                                Open <?= htmlspecialchars($broker) ?> Account
                            </a>
                        <?php endforeach; ?>
                    <?php else: ?>
                        <p class="error-text">Broker configuration is currently unavailable. Please check back later.</p>
                    <?php endif; ?>
                </div>
                <p style="text-align:center; font-size:1.4rem; margin:2rem 0; color:var(--accent);">OR</p>
                <button class="btn" onclick="openExistingModal()" style="width:80%; max-width:350px; display:block; margin: 0 auto;">I already have an account</button>
            </div>
        </div>
        
        <div id="existingModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeModal('existingModal')">×</span>
                <h2>Important Instructions</h2>
                <p><strong>1.</strong> Deposit minimum <strong>$<?= number_format($min_broker_balance, 2) ?> USD</strong> to your MT5 account.</p>
                <p><strong>2.</strong> Your capital will most likely be doubled in the specified period by management.</p>
                <p><strong>3.</strong> Do NOT withdraw or take unverified actions during the management period.</p>
                <p><strong>4.</strong> After the management period, pay the profit percentage to the account manager to remain eligible.</p>
                <div class="checkbox-container">
                    <input type="checkbox" id="agree">
                    <label for="agree">I understand and agree to the terms above</label>
                </div>
                <div id="agreeError" class="error-text" style="display:none;">Please agree to continue</div>
                <button class="btn" style="width:100%; margin-top:20px;" onclick="checkAgreement()">Continue</button>
            </div>
        </div>
        
        <div id="noDeveloperModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeModal('noDeveloperModal')">×</span>
                <h2 style="text-align:center; color:var(--accent);">Notice</h2>
                <div class="info-message">
                    <p style="font-size:1.2rem;"> No Developer or Trader is currently available</p>
                </div>
                <p style="text-align:center; font-size:1.1rem; margin:20px 0;">
                    Would you like to join HarvHub Management instead?
                </p>
                <div class="terms-box">
                    <div class="terms-item">
                        <span class="terms-label">Management Period:</span>
                        <span class="terms-value">30 Days</span>
                    </div>
                    <div class="terms-item">
                        <span class="terms-label">Server share:</span>
                        <span class="terms-value">30%</span>
                    </div>
                </div>
                <div class="checkbox-container" style="justify-content: center;">
                    <input type="checkbox" id="agreeManagement">
                    <label for="agreeManagement">I agree to the management terms</label>
                </div>
                <div id="managementAgreeError" class="error-text" style="display:none;">Please agree to the terms to continue</div>
                <button class="btn" style="width:100%; margin-top:20px;" onclick="proceedToHarvHubManagement()">Agree & Join</button>
            </div>
        </div>
        
        <div id="managementConfirmModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeModal('managementConfirmModal')">×</span>
                <h2 style="text-align:center; color:var(--accent);">Join HarvHub Management</h2>
                <div style="text-align:center; margin:20px 0;">
                    <p style="font-size:1.2rem;">You're about to join HarvHub Management with:</p>
                </div>
                <div class="terms-box">
                    <div class="terms-item">
                        <span class="terms-label">Duration:</span>
                        <span class="terms-value">30 Days</span>
                    </div>
                    <div class="terms-item">
                        <span class="terms-label">Profit Share:</span>
                        <span class="terms-value">30% to Management</span>
                    </div>
                    <div class="terms-item">
                        <span class="terms-label">Your Share:</span>
                        <span class="terms-value">70%</span>
                    </div>
                </div>
                <div class="checkbox-container" style="justify-content: center;">
                    <input type="checkbox" id="agreeFinal">
                    <label for="agreeFinal">I confirm and wish to proceed</label>
                </div>
                <div id="finalAgreeError" class="error-text" style="display:none;">Please confirm to continue</div>
                <button class="btn" style="width:100%; margin-top:20px;" onclick="proceedToRegistration()">Continue to Registration</button>
            </div>
        </div>
        
        <!-- Edit Modal (Smaller size) -->
        <div id="editModal" class="modal modal-small">
            <div class="modal-content">
                <span class="close" onclick="closeModal('editModal')">×</span>
                <h2 style="text-align:center;"> Edit Broker Details</h2>
                <p style="text-align:center; margin-bottom:20px;">Update your information while your application is pending review.</p>
                <?php if ($error): ?>
                    <p class="error-text"><?= htmlspecialchars($error) ?></p>
                <?php endif; ?>
                <form method="POST" id="editForm">
                    <input type="hidden" name="edit_insider" value="1">
                    
                    <div class="form-group">
                        <label>Select Broker</label>
                        <select name="broker" id="edit_broker" required>
                            <option value="">-- Select Broker --</option>
                            <?php foreach ($allowed_brokers as $broker): ?>
                                <option value="<?= htmlspecialchars($broker) ?>" <?= ($user_broker == $broker) ? 'selected' : '' ?>>
                                    <?= htmlspecialchars($broker) ?>
                                </option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label>Server</label>
                        <input type="text" name="server" id="edit_server" value="<?= htmlspecialchars($user_server) ?>" required>
                    </div>
                    
                    <div class="form-group">
                        <label>Login Number</label>
                        <input type="text" name="login" id="edit_login" value="<?= htmlspecialchars($user_login) ?>" required>
                    </div>
                    
                    <div class="form-group">
                        <label>MT5 Password</label>
                        <div class="password-wrapper-edit">
                            <input type="password" name="password" id="edit_pass" required>
                            <span class="password-toggle-edit" onclick="toggleEditPass()">Show</span>
                        </div>
                    </div>
                    
                    <p style="color:orange; font-weight:bold; margin-top:15px; text-align:center; font-size:0.85rem;">
                        Double-check your details before submitting. Changes will be reviewed.
                    </p>
                    
                    <button type="submit" class="btn" style="width:100%; margin-top:15px;">
                        Update & Resubmit
                    </button>
                </form>
            </div>
        </div>
        
        <div id="insiderModal" class="modal <?php echo ($just_submitted || ($logged_in_email !== '' && !$already_submitted && $error)) ? 'active' : ''; ?>">
            <div class="modal-content">
                <span class="close" onclick="closeModal('insiderModal')">×</span>
                <?php if ($already_submitted || $just_submitted): ?>
                    <div style="text-align:center; padding:3rem 1rem;">
                        <?php if ($application_status === 'blacklisted'): ?>
                            <h2 style="color:#ff6b6b;">Blacklisted</h2>
                            <p style="font-size:1.2rem; line-height:1.7; margin:1.5rem 0;">
                                Your access to this service has been restricted.
                            </p>
                        <?php elseif ($application_status === 'declined'): ?>
                            <h2 style="color:#ff6b6b;">Application Declined</h2>
                            <p style="font-size:1.2rem; line-height:1.7; margin:1.5rem 0;">
                                Your request to join insiders was declined
                            </p>
                        <?php elseif ($application_status === 'approved'): ?>
                            <h2 style="color:#90ee90;">Access Approved</h2>
                            <p style="font-size:1.2rem; line-height:1.7; margin:1.5rem 0;">
                                Your access is approved. Please click 'Go to Dashboard' on the main page.
                            </p>
                        <?php else: ?>
                            <h2 style="color:#90ee90;">Application Received</h2>
                            <p style="font-size:1.2rem; line-height:1.7; margin:1.5rem 0;">
                                We will notify you once your broker details are verified.
                            </p>
                        <?php endif; ?>
                        <button class="btn" style="margin-top:2rem; width:80%; max-width:300px;" onclick="closeModal('insiderModal')">
                            Close
                        </button>
                    </div>
                <?php else: ?>
                    <h2 style="text-align:center;">Complete Your Registration</h2>
                    <p style="text-align:center; margin-bottom:20px;">Email: <?= htmlspecialchars($logged_in_email) ?></p>
                    <?php if ($error): ?>
                        <p class="error-text"><?= htmlspecialchars($error) ?></p>
                    <?php endif; ?>
                    <form method="POST">
                        <label>Broker</label>
                        <select name="broker" required>
                            <option value="">-- Select Broker --</option>
                            <?php foreach ($allowed_brokers as $broker): ?>
                                <option value="<?= htmlspecialchars($broker) ?>" <?= (($_POST['broker'] ?? '') == $broker) ? 'selected' : '' ?>>
                                    <?= htmlspecialchars($broker) ?>
                                </option>
                            <?php endforeach; ?>
                        </select>
                        <label>Server</label>
                        <input type="text" name="server" value="<?= htmlspecialchars($_POST['server'] ?? '') ?>" required>
                        <label>Login No.</label>
                        <input type="text" name="login" value="<?= htmlspecialchars($_POST['login'] ?? '') ?>" required>
                        <label>Mt5 Password</label>
                        <div class="password-wrapper">
                            <input type="password" name="password" id="pass" required>
                            <span class="password-toggle" onclick="togglePass()">Show</span>
                        </div>
                        <p style="color:orange; font-weight:bold; margin-top:25px; text-align:center;">
                            This can only be submitted once. Double-check your details.
                        </p>
                        <button type="submit" name="submit_insider" class="btn" style="width:100%; margin-top:15px;">
                            Submit
                        </button>
                    </form>
                <?php endif; ?>
            </div>
        </div>
        
        <div id="declinedModal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closeModal('declinedModal')">×</span>
                <div style="text-align:center; padding:3rem 1rem;">
                    <h2 style="color:#ff6b6b;">Access Declined</h2>
                    <p style="font-size:1.2rem; line-height:1.7; margin:1.5rem 0;">
                        Your request to join insiders was declined
                    </p>
                    <button class="btn" style="margin-top:2rem; width:80%; max-width:300px;" onclick="closeModal('declinedModal')">
                        Close
                    </button>
                </div>
            </div>
        </div>
        
        <script>
            let refreshInterval = null;
            let isPageActive = true;
            
            async function fetchLiveUserData() {
                <?php if ($logged_in_email !== '' && !$already_submitted): ?>
                    try {
                        const response = await fetch(window.location.href, {
                            method: 'POST',
                            headers: {
                                'X-Requested-With': 'XMLHttpRequest',
                                'Content-Type': 'application/x-www-form-urlencoded',
                            },
                            credentials: 'same-origin',
                            body: 'action=get_user_status&email=' + encodeURIComponent('<?= htmlspecialchars($logged_in_email) ?>')
                        });
                        
                        if (!response.ok) return;
                        const data = await response.json();
                        
                        if (data.success) {
                            const profileStatus = document.getElementById('profileStatus');
                            const mobileStatus = document.getElementById('mobileStatus');
                            if (profileStatus) profileStatus.textContent = data.application_status || 'Not Submitted';
                            if (mobileStatus) mobileStatus.textContent = data.application_status || 'Not Submitted';
                            
                            const joinBtn = document.getElementById('joinBtn');
                            if (joinBtn) {
                                let buttonText = 'Complete registration';
                                let buttonId = 'joinBtn';
                                let buttonClass = 'btn';
                                let buttonOnclick = '';
                                
                                if (data.application_status === 'blacklisted') {
                                    buttonText = 'You will be invited';
                                    buttonId = 'blacklistedBtn';
                                    buttonClass = 'btn blacklisted';
                                } else if (data.application_status === 'approved') {
                                    buttonText = 'Go to Dashboard';
                                    buttonId = 'dashboardBtn';
                                    buttonOnclick = "window.location.href='mydashboard.php'";
                                } else if (data.application_status === 'declined') {
                                    buttonText = 'Not Eligible';
                                    buttonId = 'declinedBtn';
                                } else if (data.application_status === 'pending') {
                                    buttonText = 'Application Received';
                                    buttonId = 'submittedBtn';
                                }
                                
                                joinBtn.textContent = buttonText;
                                joinBtn.id = buttonId;
                                joinBtn.className = buttonClass;
                                if (buttonOnclick) {
                                    joinBtn.setAttribute('onclick', buttonOnclick);
                                }
                                
                                if (buttonId === 'submittedBtn') {
                                    joinBtn.onclick = function() { document.getElementById('insiderModal').classList.add('active'); };
                                } else if (buttonId === 'declinedBtn') {
                                    joinBtn.onclick = function() { document.getElementById('declinedModal').classList.add('active'); };
                                } else if (buttonId === 'blacklistedBtn') {
                                    joinBtn.onclick = function() { document.getElementById('insiderModal').classList.add('active'); };
                                }
                            }
                            
                            if (data.broker_balance !== undefined && data.profitandloss !== undefined) {
                                const liveDataDiv = document.getElementById('liveBrokerData');
                                const mobileLiveData = document.getElementById('mobileLiveData');
                                const currentBalance = parseFloat(data.broker_balance) + parseFloat(data.profitandloss);
                                const profitClass = parseFloat(data.profitandloss) >= 0 ? 'profit' : 'loss';
                                const profitSign = parseFloat(data.profitandloss) >= 0 ? '+' : '';
                                const html = `
                                    <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:5px; padding:8px 0; border-top:1px solid rgba(255,255,255,0.1);">
                                        <span>Balance: <strong>$${parseFloat(data.broker_balance).toFixed(2)}</strong></span>
                                        <span>P&L: <strong class="${profitClass}">${profitSign}$${parseFloat(data.profitandloss).toFixed(2)}</strong></span>
                                        <span style="width:100%; text-align:center; font-size:1.1rem; font-weight:bold; color:var(--accent);">Current: $${currentBalance.toFixed(2)}</span>
                                    </div>
                                `;
                                if (liveDataDiv) liveDataDiv.innerHTML = html;
                                if (mobileLiveData) mobileLiveData.innerHTML = html;
                            }
                        }
                    } catch (error) {}
                <?php endif; ?>
            }
            
            function startLiveRefresh(intervalSeconds = 15) {
                if (refreshInterval) clearInterval(refreshInterval);
                fetchLiveUserData();
                refreshInterval = setInterval(() => { if (isPageActive) fetchLiveUserData(); }, intervalSeconds * 1000);
            }
            function openSignupModal() {
                document.getElementById('signupModal').classList.add('active');
                // Focus on the email input in signup modal
                setTimeout(() => {
                    const emailInput = document.querySelector('#signupModal input[name="signup_email"]');
                    if (emailInput) emailInput.focus();
                }, 100);
            }
            
            <?php if ($logged_in_email !== '' && !$already_submitted): ?>
            document.addEventListener('DOMContentLoaded', function() { startLiveRefresh(15); });
            window.addEventListener('beforeunload', function() { if (refreshInterval) clearInterval(refreshInterval); });
            <?php endif; ?>
            
            function openEmailModal() { 
                document.getElementById('emailModal').classList.add('active'); 
                // Focus on email input
                setTimeout(() => {
                    const emailInput = document.getElementById('loginEmailInput');
                    if (emailInput) emailInput.focus();
                }, 100);
            }
            function openBrokerModal() { document.getElementById('brokerModal').classList.add('active'); }
            function openEditModal() { document.getElementById('editModal').classList.add('active'); }
            
            function openExistingModal() { 
                closeModal('brokerModal'); 
                document.getElementById('existingModal').classList.add('active'); 
            }
            
            function checkAgreement() {
                if (document.getElementById('agree').checked) {
                    closeModal('existingModal');
                    document.getElementById('noDeveloperModal').classList.add('active');
                } else {
                    document.getElementById('agreeError').style.display = 'block';
                }
            }
            
            function proceedToHarvHubManagement() {
                if (document.getElementById('agreeManagement').checked) {
                    closeModal('noDeveloperModal');
                    document.getElementById('managementConfirmModal').classList.add('active');
                    document.getElementById('managementAgreeError').style.display = 'none';
                } else {
                    document.getElementById('managementAgreeError').style.display = 'block';
                }
            }
            
            function proceedToRegistration() {
                if (document.getElementById('agreeFinal').checked) {
                    closeModal('managementConfirmModal');
                    document.getElementById('insiderModal').classList.add('active');
                    document.getElementById('finalAgreeError').style.display = 'none';
                } else {
                    document.getElementById('finalAgreeError').style.display = 'block';
                }
            }
            
            function closeModal(id) { 
                document.getElementById(id).classList.remove('active'); 
                if(id === 'existingModal') {
                    document.getElementById('agree').checked = false;
                    document.getElementById('agreeError').style.display = 'none';
                }
                if(id === 'noDeveloperModal') {
                    document.getElementById('agreeManagement').checked = false;
                    document.getElementById('managementAgreeError').style.display = 'none';
                }
                if(id === 'managementConfirmModal') {
                    document.getElementById('agreeFinal').checked = false;
                    document.getElementById('finalAgreeError').style.display = 'none';
                }
                if(id === 'editModal') {
                    document.getElementById('agreeError').style.display = 'none';
                }
                if(id === 'emailModal') {
                    // Reset the form when closing
                    const passkeyContainer = document.getElementById('passkeyFieldContainer');
                    if (passkeyContainer) passkeyContainer.remove();
                    const errorEl = document.querySelector('#emailModal .error-text');
                    if (errorEl) errorEl.remove();
                    const loginBtn = document.querySelector('#emailModal button[type="submit"]');
                    if (loginBtn) loginBtn.textContent = 'Continue';
                    const emailInput = document.getElementById('loginEmailInput');
                    if (emailInput) emailInput.value = '';
                }
            }
            
            function togglePass() {
                const p = document.getElementById('pass');
                const t = document.querySelector('.password-toggle');
                if (p.type === 'password') { p.type = 'text'; t.textContent = 'Hide'; }
                else { p.type = 'password'; t.textContent = 'Show'; }
            }
            
            function toggleEditPass() {
                const p = document.getElementById('edit_pass');
                const t = document.querySelector('.password-toggle-edit');
                if (p.type === 'password') { p.type = 'text'; t.textContent = 'Hide'; }
                else { p.type = 'password'; t.textContent = 'Show'; }
            }
            
            // Login form handling
            document.addEventListener('DOMContentLoaded', function() {
                const loginForm = document.getElementById('loginForm');
                if (loginForm) {
                    loginForm.addEventListener('submit', function(e) {
                        const emailInput = document.getElementById('loginEmailInput');
                        const passkeyInput = document.getElementById('loginPasskeyInput');
                        
                        // If passkey field exists, make sure it's required
                        if (passkeyInput) {
                            passkeyInput.required = true;
                        }
                    });
                }
            });
            
            window.onclick = function(e) {
                if (e.target.classList.contains('modal')) e.target.classList.remove('active');
            };
            
            document.addEventListener('DOMContentLoaded', function() {
                const profileIcon = document.getElementById('profileIcon');
                const profileCard = document.getElementById('profileCard');
                const joinBtn = document.getElementById('joinBtn');
                
                if (profileIcon && profileCard) {
                    profileIcon.addEventListener('click', function(e) {
                        e.stopPropagation(); 
                        profileCard.classList.toggle('active');
                        profileIcon.classList.toggle('active');
                    });
                    document.addEventListener('click', function(e) {
                        if (profileCard.classList.contains('active') && !profileCard.contains(e.target) && e.target !== profileIcon) {
                            profileCard.classList.remove('active');
                            profileIcon.classList.remove('active');
                        }
                    });
                    profileCard.addEventListener('click', function(e) { e.stopPropagation(); });
                }
                
                if (joinBtn) {
                    joinBtn.addEventListener('click', function() {
                        <?php if ($logged_in_email === ''): ?>
                            openEmailModal();
                        <?php else: ?>
                            openBrokerModal();
                        <?php endif; ?>
                    });
                }
                
                const submittedBtn = document.getElementById('submittedBtn');
                const declinedBtn = document.getElementById('declinedBtn');
                const blacklistedBtn = document.getElementById('blacklistedBtn');
                
                if (submittedBtn) submittedBtn.addEventListener('click', function() { document.getElementById('insiderModal').classList.add('active'); });
                if (declinedBtn) declinedBtn.addEventListener('click', function() { document.getElementById('declinedModal').classList.add('active'); });
                if (blacklistedBtn) blacklistedBtn.addEventListener('click', function() { document.getElementById('insiderModal').classList.add('active'); });
                
                <?php if ($just_submitted || ($logged_in_email !== '' && $application_status === 'blacklisted' && $already_submitted)): ?>
                    document.getElementById('insiderModal').classList.add('active');
                <?php endif; ?>
                
                // Auto-open email modal if there's a login error or signup modal should show
                <?php if ($show_passkey_field || $login_error): ?>
                    openEmailModal();
                <?php endif; ?>
            });
            
            // Add to your existing AJAX handling
            function showLoadingForAjax() {
                if (window.loadingManager) {
                    window.loadingManager.show();
                    window.loadingManager.startProgress();
                    window.loadingManager.isComplete = false;
                }
            }

            function hideLoadingForAjax() {
                if (window.loadingManager) {
                    window.loadingManager.completeLoading();
                }
            }

            // Example usage with your existing fetch calls
            async function fetchLiveUserData() {
                showLoadingForAjax(); // Show loading before fetch
                
                try {
                    const response = await fetch(window.location.href, {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        credentials: 'same-origin',
                        body: 'action=get_user_status&email=' + encodeURIComponent('<?= htmlspecialchars($logged_in_email) ?>')
                    });
                    
                    if (!response.ok) return;
                    const data = await response.json();
                    // ... process data
                } catch (error) {
                    // Handle error
                } finally {
                    hideLoadingForAjax(); // Hide loading after complete
                }
            }
        </script>
    </div>
</body>
</html>
