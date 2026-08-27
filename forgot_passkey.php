<?php
session_start();

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

// ==================== SMTP CONFIGURATION ====================
// Using PHPMailer - make sure to include it
// For this standalone script, we'll use the built-in mail() function as fallback
// But the recommended approach is PHPMailer with Gmail SMTP

// ==================== DETERMINE SOURCE ====================
// Check if request came from mydashboard.php
$source = isset($_GET['source']) ? $_GET['source'] : (isset($_SESSION['reset_source']) ? $_SESSION['reset_source'] : 'index');
// If source is not explicitly set but user is logged in, assume dashboard
if ($source === 'index' && isset($_SESSION['user_email']) && !empty($_SESSION['user_email'])) {
    $source = 'dashboard';
}
// Store in session for persistence
$_SESSION['reset_source'] = $source;

// If source is 'dashboard' and we have a logged-in email, pre-fill it
$prefill_email = '';
if ($source === 'dashboard' && isset($_SESSION['user_email'])) {
    $prefill_email = $_SESSION['user_email'];
}

// ==================== FUNCTIONS ====================
function generateResetCode() {
    return str_pad(rand(0, 999999), 6, '0', STR_PAD_LEFT);
}

function sendResetEmail($email, $code) {
    // PHPMailer setup - make sure the paths are correct
    require_once 'PHPMailer/src/PHPMailer.php';
    require_once 'PHPMailer/src/SMTP.php';
    require_once 'PHPMailer/src/Exception.php';
    
    $mail = new PHPMailer\PHPMailer\PHPMailer(true);
    
    try {
        // Server settings
        $mail->isSMTP();
        $mail->Host       = 'smtp.gmail.com';
        $mail->SMTPAuth   = true;
        $mail->Username   = 'techknowdgeteam@gmail.com';  // YOUR GMAIL
        $mail->Password   = 'rqcrossbioujepda';           // YOUR APP PASSWORD (no spaces)
        $mail->SMTPSecure = PHPMailer\PHPMailer\PHPMailer::ENCRYPTION_STARTTLS;
        $mail->Port       = 587;
        
        // Recipients
        $mail->setFrom('techknowdgeteam@gmail.com', 'HarvHub Support');
        $mail->addAddress($email); // Sends to the user requesting reset
        
        // Content
        $mail->isHTML(true);
        $mail->Subject = 'Password Reset Code - HarvHub';
        $mail->Body    = "
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; color: #333; }
                    .container { max-width: 500px; margin: 0 auto; padding: 20px; background: #f9f9f9; border-radius: 10px; }
                    .code { font-size: 32px; font-weight: bold; color: #2e8b57; text-align: center; padding: 20px; background: #fff; border-radius: 8px; margin: 20px 0; letter-spacing: 5px; }
                    .footer { font-size: 12px; color: #999; text-align: center; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class='container'>
                    <h2 style='text-align:center; color:#2e8b57;'>HarvHub</h2>
                    <h3 style='text-align:center;'>Password Reset Request</h3>
                    <p>We received a request to reset your password. Enter the following verification code:</p>
                    <div class='code'>$code</div>
                    <p>If you didn't request this, please ignore this email.</p>
                    <div class='footer'>HarvHub Security</div>
                </div>
            </body>
            </html>
        ";
        $mail->AltBody = "Your password reset code is: $code\n\nHarvHub Security";
        
        $mail->send();
        return true;
    } catch (Exception $e) {
        error_log("Mail Error: " . $mail->ErrorInfo);
        return false;
    }
}

function storeResetCode($pdo, $email, $code) {
    // Delete any existing reset codes for this email
    $stmt = $pdo->prepare("DELETE FROM password_resets WHERE email = ?");
    $stmt->execute([$email]);
    
    // Insert new reset code with no expiry
    $stmt = $pdo->prepare("INSERT INTO password_resets (email, reset_code, expires_at) VALUES (?, ?, DATE_ADD(NOW(), INTERVAL 1 YEAR))");
    return $stmt->execute([$email, $code]);
}

function verifyResetCode($pdo, $email, $code) {
    $stmt = $pdo->prepare("
        SELECT id, reset_code, expires_at, used 
        FROM password_resets 
        WHERE email = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    ");
    $stmt->execute([$email]);
    $record = $stmt->fetch(PDO::FETCH_ASSOC);
    
    if (!$record) {
        return ['valid' => false, 'message' => 'No reset request found.'];
    }
    
    if ($record['used'] == 1) {
        return ['valid' => false, 'message' => 'This code has already been used.'];
    }
    
    if ($record['reset_code'] !== $code) {
        return ['valid' => false, 'message' => 'Invalid verification code. Please try again.'];
    }
    
    return ['valid' => true, 'message' => 'Code verified successfully.'];
}

function markCodeAsUsed($pdo, $email) {
    $stmt = $pdo->prepare("UPDATE password_resets SET used = 1 WHERE email = ? ORDER BY created_at DESC LIMIT 1");
    return $stmt->execute([$email]);
}

function updatePasskey($pdo, $email, $new_passkey) {
    $hashed = password_hash($new_passkey, PASSWORD_DEFAULT);
    $stmt = $pdo->prepare("UPDATE insiders SET passkey = ? WHERE email = ?");
    return $stmt->execute([$hashed, $email]);
}

function maskEmail($email) {
    $parts = explode('@', $email);
    $username = $parts[0];
    $domain = $parts[1] ?? '';
    
    if (strlen($username) <= 2) {
        $masked = $username;
    } else {
        $masked = substr($username, 0, 2) . str_repeat('*', strlen($username) - 4) . substr($username, -2);
    }
    
    return $masked . '@' . $domain;
}

// ==================== HANDLE ACTIONS ====================
$email = $_SESSION['reset_email'] ?? $prefill_email;
$step = $_SESSION['reset_step'] ?? 'request'; // request, verify, reset
$error = $_SESSION['reset_error'] ?? '';
$success = $_SESSION['reset_success'] ?? '';

// ==================== HANDLE REQUEST CODE ====================
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'request_reset') {
    $email = trim(strtolower($_POST['reset_email'] ?? ''));
    
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $_SESSION['reset_error'] = 'Please enter a valid email address.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    // Check if user exists
    $stmt = $pdo->prepare("SELECT id, email FROM insiders WHERE email = ? LIMIT 1");
    $stmt->execute([$email]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);
    
    if (!$user) {
        $_SESSION['reset_error'] = 'No account found with this email address.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    // Generate and store reset code
    $code = generateResetCode();
    
    if (!storeResetCode($pdo, $email, $code)) {
        $_SESSION['reset_error'] = 'Failed to generate reset code. Please try again.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    // Send email
    if (sendResetEmail($email, $code)) {
        $_SESSION['reset_email'] = $email;
        $_SESSION['reset_step'] = 'verify';
        $_SESSION['reset_success'] = 'A verification code has been sent to your email.';
    } else {
        $_SESSION['reset_error'] = 'Failed to send email. Please try again or contact support.';
    }
    
    header('Location: forgot_passkey.php?source=' . $source);
    exit;
}

// ==================== HANDLE VERIFY CODE ====================
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'verify_code') {
    $code = trim($_POST['reset_code'] ?? '');
    $email = $_SESSION['reset_email'] ?? '';
    
    if (empty($email)) {
        $_SESSION['reset_error'] = 'Session expired. Please start over.';
        $_SESSION['reset_step'] = 'request';
        unset($_SESSION['reset_email']);
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    if (empty($code) || strlen($code) !== 6) {
        $_SESSION['reset_error'] = 'Please enter the complete 6-digit verification code.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    $result = verifyResetCode($pdo, $email, $code);
    
    if ($result['valid']) {
        markCodeAsUsed($pdo, $email);
        $_SESSION['reset_step'] = 'reset';
        $_SESSION['reset_success'] = 'Code verified! Please set your new passkey.';
        unset($_SESSION['reset_error']);
    } else {
        $_SESSION['reset_error'] = $result['message'];
    }
    
    header('Location: forgot_passkey.php?source=' . $source);
    exit;
}

// ==================== HANDLE RESET PASSKEY ====================
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'reset_passkey') {
    $new_passkey = $_POST['new_passkey'] ?? '';
    $confirm_passkey = $_POST['confirm_passkey'] ?? '';
    $email = $_SESSION['reset_email'] ?? '';
    
    if (empty($email) || $_SESSION['reset_step'] !== 'reset') {
        $_SESSION['reset_error'] = 'Session expired. Please start over.';
        $_SESSION['reset_step'] = 'request';
        unset($_SESSION['reset_email']);
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    if (empty($new_passkey) || strlen($new_passkey) < 4) {
        $_SESSION['reset_error'] = 'Passkey must be at least 4 characters long.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    if ($new_passkey !== $confirm_passkey) {
        $_SESSION['reset_error'] = 'Passkeys do not match.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
    
    if (updatePasskey($pdo, $email, $new_passkey)) {
        // Clear reset session
        unset($_SESSION['reset_email']);
        unset($_SESSION['reset_step']);
        unset($_SESSION['reset_success']);
        $_SESSION['reset_error'] = '';
        
        // Set success flag for the modal
        $_SESSION['reset_complete'] = true;
        $_SESSION['reset_complete_email'] = $email;
        
        header('Location: forgot_passkey.php?source=' . $source . '&reset_complete=1');
        exit;
    } else {
        $_SESSION['reset_error'] = 'Failed to update passkey. Please try again.';
        header('Location: forgot_passkey.php?source=' . $source);
        exit;
    }
}

// ==================== HANDLE RESEND CODE ====================
if (isset($_GET['resend']) && $_GET['resend'] === '1') {
    $email = $_SESSION['reset_email'] ?? '';
    
    if (!empty($email)) {
        $code = generateResetCode();
        
        if (storeResetCode($pdo, $email, $code)) {
            if (sendResetEmail($email, $code)) {
                $_SESSION['reset_success'] = 'A new verification code has been sent to your email.';
            } else {
                $_SESSION['reset_error'] = 'Failed to send email. Please try again.';
            }
        } else {
            $_SESSION['reset_error'] = 'Failed to generate new code. Please try again.';
        }
    }
    
    header('Location: forgot_passkey.php?source=' . $source);
    exit;
}

// ==================== HANDLE CANCEL ====================
if (isset($_GET['cancel'])) {
    // Determine where to redirect based on source
    $redirect_url = ($source === 'dashboard') ? 'mydashboard.php' : 'index.php';
    unset($_SESSION['reset_email']);
    unset($_SESSION['reset_step']);
    unset($_SESSION['reset_success']);
    unset($_SESSION['reset_error']);
    header('Location: ' . $redirect_url);
    exit;
}

// ==================== GET CURRENT STATE ====================
$email = $_SESSION['reset_email'] ?? $prefill_email;
$step = $_SESSION['reset_step'] ?? 'request';
$error = $_SESSION['reset_error'] ?? '';
$success = $_SESSION['reset_success'] ?? '';
$reset_complete = isset($_GET['reset_complete']) || isset($_SESSION['reset_complete']);
$complete_email = $_SESSION['reset_complete_email'] ?? '';

if ($reset_complete) {
    unset($_SESSION['reset_complete']);
    unset($_SESSION['reset_complete_email']);
}

$maskedEmail = !empty($email) ? maskEmail($email) : '';

// Determine back link based on source
$back_link = ($source === 'dashboard') ? 'mydashboard.php' : 'index.php';
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Forgot Passkey - HarvHub</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    /* ==================== CSS VARIABLES ==================== */
    :root {
        --bg-primary: #000;
        --bg-secondary: rgba(20, 20, 30, 0.95);
        --bg-input: #1a1a2e;
        --bg-modal: #1a1a2e;
        --bg-overlay-start: #1a0033;
        --bg-overlay-end: #000033;
        --text-primary: #e4e6eb;
        --text-secondary: #aaa;
        --text-muted: #888;
        --text-dark: #555;
        --border-color: #333;
        --border-light: rgba(255,255,255,0.05);
        --shadow-color: rgba(0,0,0,0.8);
        --input-focus: #2e8b57;
        --success-color: #90ee90;
        --error-color: #ff6b6b;
        --error-bg: rgba(255, 107, 107, 0.1);
        --success-bg: rgba(46, 139, 87, 0.1);
        --source-badge-bg: rgba(46, 139, 87, 0.2);
        --modal-overlay: rgba(0,0,0,0.7);
        --btn-text: #000;
        --scrollbar-track: #1a1a2e;
        --scrollbar-thumb: #2e8b57;
        --scrollbar-thumb-hover: #3a9b67;
    }

    /* ==================== LIGHT MODE OVERRIDES ==================== */
    @media (prefers-color-scheme: light) {
        :root {
            --bg-primary: #f0f2f5;
            --bg-secondary: rgba(255, 255, 255, 0.95);
            --bg-input: #ffffff;
            --bg-modal: #ffffff;
            --bg-overlay-start: #e8f0e8;
            --bg-overlay-end: #d4e8d4;
            --text-primary: #1a1a2e;
            --text-secondary: #555;
            --text-muted: #777;
            --text-dark: #333;
            --border-color: #ddd;
            --border-light: rgba(0,0,0,0.08);
            --shadow-color: rgba(0,0,0,0.15);
            --input-focus: #2e8b57;
            --success-color: #2e8b57;
            --error-color: #dc3545;
            --error-bg: rgba(220, 53, 69, 0.08);
            --success-bg: rgba(46, 139, 87, 0.08);
            --source-badge-bg: rgba(46, 139, 87, 0.15);
            --modal-overlay: rgba(0,0,0,0.4);
            --btn-text: #fff;
            --scrollbar-track: #e8e8e8;
            --scrollbar-thumb: #2e8b57;
            --scrollbar-thumb-hover: #3a9b67;
        }
        
        /* Light mode specific overrides for better contrast */
        .container {
            border: 1px solid rgba(0,0,0,0.08);
            box-shadow: 0 20px 60px rgba(0,0,0,0.1);
        }
        
        input[type="email"],
        input[type="password"] {
            border: 1px solid #ddd;
            background: #ffffff;
            color: #1a1a2e;
        }
        
        input[type="email"]::placeholder,
        input[type="password"]::placeholder {
            color: #999;
        }
        
        input[type="email"]:focus,
        input[type="password"]:focus {
            border-color: #2e8b57;
            box-shadow: 0 0 0 3px rgba(46, 139, 87, 0.1);
        }
        
        .btn {
            color: #fff;
            background: #2e8b57;
        }
        
        .btn:hover {
            background: #3a9b67;
        }
        
        .btn-secondary {
            color: #555;
            border: 1px solid #ddd;
            background: transparent;
        }
        
        .btn-secondary:hover {
            background: rgba(0,0,0,0.03);
        }
        
        .error-message {
            color: #dc3545;
            background: rgba(220, 53, 69, 0.08);
            border-left: 3px solid #dc3545;
        }
        
        .success-message {
            color: #2e8b57;
            background: rgba(46, 139, 87, 0.08);
            border-left: 3px solid #2e8b57;
        }
        
        .code-input-container input {
            border: 1px solid #ddd;
            background: #ffffff;
            color: #1a1a2e;
        }
        
        .code-input-container input:focus {
            border-color: #2e8b57;
            box-shadow: 0 0 15px rgba(46, 139, 87, 0.15);
        }
        
        .password-toggle {
            color: #999;
        }
        
        .password-toggle:hover {
            color: #2e8b57;
        }
        
        .modal-content {
            background: #ffffff;
            border: 1px solid rgba(46, 139, 87, 0.2);
            box-shadow: 0 20px 60px rgba(0,0,0,0.2);
        }
        
        .modal-content h2 {
            color: #2e8b57;
        }
        
        .modal-content p {
            color: #555;
        }
        
        .source-badge {
            background: rgba(46, 139, 87, 0.15);
            color: #2e8b57;
        }
        
        .email-display {
            background: rgba(46, 139, 87, 0.05);
            color: #2e8b57;
        }
        
        .back-link a {
            color: #2e8b57;
        }
        
        .resend-link a {
            color: #2e8b57;
        }
        
        .footer {
            color: #999;
        }
        
        .info-text {
            color: #777;
        }
        
        label {
            color: #555;
        }
        
        .subtitle {
            color: #777;
        }
        
        .description {
            color: #555;
        }
        
        .email-prefill-hint {
            color: #777;
        }
        
        .modal-overlay {
            background: rgba(0,0,0,0.4);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
        }
        
        /* Light mode scrollbar */
        ::-webkit-scrollbar-track {
            background: #f0f0f0;
        }
        ::-webkit-scrollbar-thumb {
            background: #2e8b57;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #3a9b67;
        }
    }

    /* ==================== DARK MODE OVERRIDES (Default) ==================== */
    @media (prefers-color-scheme: dark) {
        input[type="email"],
        input[type="password"] {
            border: 1px solid #333;
            background: #1a1a2e;
            color: #fff;
        }
        
        input[type="email"]::placeholder,
        input[type="password"]::placeholder {
            color: #666;
        }
        
        input[type="email"]:focus,
        input[type="password"]:focus {
            border-color: #2e8b57;
            box-shadow: 0 0 0 3px rgba(46, 139, 87, 0.15);
        }
        
        .btn {
            color: #000;
            background: #2e8b57;
        }
        
        .btn:hover {
            background: #3a9b67;
        }
        
        .btn-secondary {
            color: #888;
            border: 1px solid #333;
            background: transparent;
        }
        
        .btn-secondary:hover {
            background: rgba(255,255,255,0.05);
        }
        
        .code-input-container input {
            border: 1px solid #333;
            background: #1a1a2e;
            color: #fff;
        }
        
        .code-input-container input:focus {
            border-color: #2e8b57;
            box-shadow: 0 0 15px rgba(46, 139, 87, 0.2);
        }
        
        .modal-content {
            background: #1a1a2e;
            border: 1px solid rgba(46, 139, 87, 0.3);
            box-shadow: 0 20px 60px rgba(0,0,0,0.9);
        }
        
        .modal-overlay {
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }
    }

    /* ==================== BASE STYLES ==================== */
    * { 
        margin: 0; 
        padding: 0; 
        box-sizing: border-box; 
    }
    
    html, body {
        height: 100%;
        overflow: hidden;
        position: fixed;
        width: 100%;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background: var(--bg-primary);
        color: var(--text-primary);
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
        position: relative;
        -webkit-overflow-scrolling: none;
        overscroll-behavior: none;
        transition: background 0.3s ease, color 0.3s ease;
    }
    
    body::before {
        content: "";
        position: absolute;
        inset: 0;
        background: 
            radial-gradient(circle at 20% 80%, var(--bg-overlay-start) 0%, transparent 50%),
            radial-gradient(circle at 80% 20%, var(--bg-overlay-end) 0%, transparent 50%),
            url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><circle cx="10" cy="10" r="1" fill="%23666"/><circle cx="30" cy="70" r="1.5" fill="%23666"/><circle cx="70" cy="30" r="1" fill="%23666"/><circle cx="90" cy="80" r="1.2" fill="%23666"/><circle cx="50" cy="50" r="1.8" fill="%23666"/></svg>') repeat;
        background-size: cover, cover, 120px 120px;
        opacity: 0.5;
        pointer-events: none;
        z-index: 0;
        transition: opacity 0.3s ease;
    }
    
    @media (prefers-color-scheme: light) {
        body::before {
            opacity: 0.3;
            background: 
                radial-gradient(circle at 20% 80%, #d4e8d4 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, #e8f0e8 0%, transparent 50%),
                url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><circle cx="10" cy="10" r="1" fill="%23999"/><circle cx="30" cy="70" r="1.5" fill="%23999"/><circle cx="70" cy="30" r="1" fill="%23999"/><circle cx="90" cy="80" r="1.2" fill="%23999"/><circle cx="50" cy="50" r="1.8" fill="%23999"/></svg>') repeat;
            background-size: cover, cover, 120px 120px;
        }
    }
    
    /* ==================== SCROLLBAR ==================== */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: var(--scrollbar-track);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb {
        background: var(--scrollbar-thumb);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: var(--scrollbar-thumb-hover);
    }
    
    /* ==================== CONTAINER ==================== */
    .container {
        background: var(--bg-secondary);
        border-radius: 20px;
        padding: 30px 25px;
        max-width: 500px;
        width: 100%;
        position: relative;
        z-index: 1;
        box-shadow: 0 20px 60px var(--shadow-color);
        border: 1px solid var(--border-light);
        backdrop-filter: blur(10px);
        max-height: 95vh;
        overflow-y: auto;
        overscroll-behavior: contain;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: thin;
        scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
        transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
    }
    
    .subtitle {
        text-align: center;
        color: var(--text-muted);
        margin-bottom: 20px;
        font-size: 0.9rem;
        transition: color 0.3s ease;
    }
    
    h2 {
        color: #2e8b57;
        margin-bottom: 8px;
        text-align: center;
        font-size: 1.2rem;
    }
    
    .description {
        text-align: center;
        color: var(--text-secondary);
        font-size: 0.9rem;
        margin-bottom: 20px;
        line-height: 1.5;
        transition: color 0.3s ease;
    }
    
    label {
        display: block;
        font-weight: 600;
        margin-bottom: 5px;
        color: var(--text-secondary);
        font-size: 0.85rem;
        transition: color 0.3s ease;
    }
    
    input[type="email"],
    input[type="password"] {
        width: 100%;
        padding: 12px 14px;
        border-radius: 10px;
        font-size: 0.95rem;
        transition: border-color 0.3s ease, background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
        -webkit-appearance: none;
        appearance: none;
    }
    
    input[type="email"]:focus,
    input[type="password"]:focus {
        outline: none;
        border-color: var(--input-focus);
        box-shadow: 0 0 0 3px rgba(46, 139, 87, 0.1);
    }
    
    .btn {
        width: 100%;
        padding: 12px;
        font-weight: bold;
        font-size: 0.95rem;
        border: none;
        border-radius: 10px;
        cursor: pointer;
        transition: all 0.3s ease;
        margin-top: 5px;
        -webkit-tap-highlight-color: transparent;
    }
    
    .btn:hover {
        transform: scale(1.01);
        opacity: 0.9;
    }
    
    .btn:active {
        transform: scale(0.98);
    }
    
    .btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
        transform: none;
    }
    
    .btn-secondary {
        padding: 10px;
        transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease;
    }
    
    .btn-secondary:hover {
        transform: none;
    }
    
    .error-message {
        text-align: center;
        margin: 10px 0;
        font-size: 0.85rem;
        padding: 8px 12px;
        border-radius: 8px;
        border-left: 3px solid var(--error-color);
        word-break: break-word;
        transition: color 0.3s ease, background 0.3s ease;
    }
    
    .success-message {
        text-align: center;
        margin: 10px 0;
        font-size: 0.85rem;
        padding: 8px 12px;
        border-radius: 8px;
        border-left: 3px solid var(--input-focus);
        word-break: break-word;
        transition: color 0.3s ease, background 0.3s ease;
    }
    
    .info-text {
        color: var(--text-muted);
        font-size: 0.8rem;
        text-align: center;
        margin: 12px 0;
        transition: color 0.3s ease;
    }
    
    .back-link {
        text-align: center;
        margin-top: 15px;
    }
    
    .back-link a {
        color: #2e8b57;
        text-decoration: none;
        font-size: 0.85rem;
        transition: opacity 0.3s ease;
    }
    
    .back-link a:hover {
        text-decoration: underline;
        opacity: 0.8;
    }
    
    .code-input-container {
        display: flex;
        gap: 8px;
        justify-content: center;
        margin: 15px 0 10px;
        flex-wrap: nowrap;
    }
    
    .code-input-container input {
        width: 45px;
        height: 50px;
        text-align: center;
        font-size: 1.4rem;
        font-weight: bold;
        border-radius: 10px;
        transition: border-color 0.3s ease, background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
        padding: 0;
        -webkit-appearance: none;
        appearance: none;
        -moz-appearance: textfield;
        flex-shrink: 0;
    }
    
    .code-input-container input::-webkit-outer-spin-button,
    .code-input-container input::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
    }
    
    .code-input-container input:focus {
        outline: none;
        border-color: var(--input-focus);
        box-shadow: 0 0 15px rgba(46, 139, 87, 0.15);
    }
    
    .code-input-container input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .code-input-container input.expired {
        border-color: var(--error-color);
        opacity: 0.5;
    }
    
    .resend-link {
        text-align: center;
        margin: 12px 0 5px;
    }
    
    .resend-link a {
        color: #2e8b57;
        text-decoration: none;
        font-size: 0.85rem;
        transition: opacity 0.3s ease;
    }
    
    .resend-link a:hover {
        text-decoration: underline;
        opacity: 0.8;
    }
    
    .email-display {
        text-align: center;
        font-weight: bold;
        font-size: 0.95rem;
        margin: 3px 0 12px;
        padding: 6px 12px;
        border-radius: 8px;
        word-break: break-all;
        transition: background 0.3s ease, color 0.3s ease;
    }
    
    .footer {
        text-align: center;
        margin-top: 15px;
        font-size: 0.7rem;
        transition: color 0.3s ease;
    }
    
    .password-wrapper {
        position: relative;
        margin-bottom: 10px;
    }
    
    .password-wrapper input {
        padding-right: 55px;
    }
    
    .password-toggle {
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        cursor: pointer;
        font-size: 0.8rem;
        user-select: none;
        background: transparent;
        border: none;
        padding: 4px 8px;
        border-radius: 5px;
        transition: color 0.2s ease;
        -webkit-tap-highlight-color: transparent;
    }
    
    .password-toggle:active {
        color: var(--input-focus);
    }
    
    .source-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.7rem;
        margin-bottom: 15px;
        text-align: center;
        width: 100%;
        transition: background 0.3s ease, color 0.3s ease;
    }
    
    .email-prefill-hint {
        text-align: center;
        font-size: 0.8rem;
        margin-bottom: 15px;
        transition: color 0.3s ease;
    }
    
    .modal-overlay {
        display: none;
        position: fixed;
        inset: 0;
        align-items: center;
        justify-content: center;
        z-index: 1000;
        padding: 20px;
        overflow: hidden;
        transition: background 0.3s ease, backdrop-filter 0.3s ease;
    }
    
    .modal-overlay.active {
        display: flex;
    }
    
    .modal-content {
        border-radius: 20px;
        padding: 30px 25px;
        max-width: 450px;
        width: 100%;
        text-align: center;
        max-height: 90vh;
        overflow-y: auto;
        transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
    }
    
    .modal-content .icon {
        font-size: 3.5rem;
        margin-bottom: 12px;
    }
    
    .modal-content p {
        margin-bottom: 20px;
        line-height: 1.5;
        font-size: 0.95rem;
        transition: color 0.3s ease;
    }
    
    /* ==================== RESPONSIVE ==================== */
    @media (max-width: 480px) {
        .container {
            padding: 20px 15px;
            max-height: 90vh;
        }
        .code-input-container input {
            width: 38px;
            height: 44px;
            font-size: 1.2rem;
        }
        .code-input-container {
            gap: 5px;
        }
        h2 {
            font-size: 1.1rem;
        }
        input[type="email"],
        input[type="password"] {
            padding: 10px 12px;
            font-size: 0.9rem;
        }
        .btn {
            padding: 10px;
            font-size: 0.9rem;
        }
        .modal-content {
            padding: 25px 20px;
        }
        .modal-content .icon {
            font-size: 3rem;
        }
    }
    
    @media (max-width: 380px) {
        .code-input-container input {
            width: 32px;
            height: 38px;
            font-size: 1rem;
        }
        .code-input-container {
            gap: 4px;
        }
        .container {
            padding: 15px 12px;
        }
        .email-display {
            font-size: 0.8rem;
            padding: 4px 8px;
        }
        .description {
            font-size: 0.8rem;
        }
    }
    
    @media (min-width: 768px) {
        .container {
            padding: 40px 35px;
        }
        .code-input-container input {
            width: 55px;
            height: 60px;
            font-size: 1.6rem;
        }
        .code-input-container {
            gap: 12px;
        }
    }
    
    /* Prevent zoom on input focus */
    input {
        font-size: 16px !important;
    }
    
    /* Disable text selection */
    .no-select {
        user-select: none;
        -webkit-user-select: none;
    }
</style>
</head>
<body>

<div class="container">
    <?php if ($step === 'request'): ?>
        <!-- STEP 1: Request Reset Code -->
        <h2>Forgot Passkey?</h2>
        
        <?php if ($source === 'dashboard'): ?>
            <p class="description">We'll send a verification code to <strong><?= htmlspecialchars($prefill_email) ?></strong> to reset your passkey.</p>
        <?php else: ?>
            <p class="description">Enter the email address associated with your account. We'll send a verification code to reset your passkey.</p>
        <?php endif; ?>
        
        <?php if (!empty($error)): ?>
            <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>
        
        <form method="POST" action="forgot_passkey.php?source=<?= htmlspecialchars($source) ?>" id="requestForm">
            <input type="hidden" name="action" value="request_reset">
            
            <?php if ($source === 'dashboard'): ?>
                <input type="hidden" name="reset_email" value="<?= htmlspecialchars($prefill_email) ?>">
            <?php else: ?>
                <label for="reset_email">Email Address</label>
                <input type="email" name="reset_email" id="reset_email" placeholder="youremail@gmail.com" value="<?= htmlspecialchars($email) ?>" required>
            <?php endif; ?>
            
            <button type="submit" class="btn">Send Verification Code</button>
        </form>
        
        <div class="back-link">
            <a href="<?= $back_link ?>">Back to <?= ($source === 'dashboard') ? 'Dashboard' : 'Login' ?></a>
        </div>

    <?php elseif ($step === 'verify'): ?>
        <!-- STEP 2: Verify Code -->
        <h2>Reset Passkey</h2>
        <p class="success-message">We sent a 6-digit verification code to <?= htmlspecialchars($maskedEmail) ?></p>
        
        <?php if (!empty($error)): ?>
            <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>
        
        <form method="POST" action="forgot_passkey.php?source=<?= htmlspecialchars($source) ?>" id="verifyForm">
            <input type="hidden" name="action" value="verify_code">
            <label>Enter 6-Digit Code</label>
            <div class="code-input-container" id="codeContainer">
                <input type="text" maxlength="1" class="code-input" data-index="0" autofocus required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="1" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="2" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="3" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="4" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="5" required inputmode="numeric" pattern="[0-9]">
            </div>
            <input type="hidden" name="reset_code" id="resetCodeHidden" value="">
            
            <button type="submit" class="btn" id="verifyBtn">Verify Code</button>
        </form>
        
        <div class="resend-link">
            <a href="forgot_passkey.php?resend=1&source=<?= htmlspecialchars($source) ?>" id="resendLink">Resend Code</a> &nbsp;|&nbsp;
            <a href="forgot_passkey.php?cancel=1&source=<?= htmlspecialchars($source) ?>">Cancel</a>
        </div>

    <?php elseif ($step === 'reset'): ?>
        <!-- STEP 3: Set New Passkey -->
        <h2>Set New Passkey</h2>
        <p class="description">Create a new passkey for your account. Make sure it's something you'll remember.</p>
        
        <?php if (!empty($error)): ?>
            <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>
        
        <?php if (!empty($success)): ?>
            <div class="success-message"><?= htmlspecialchars($success) ?></div>
        <?php endif; ?>
        
        <form method="POST" action="forgot_passkey.php?source=<?= htmlspecialchars($source) ?>" id="resetForm">
            <input type="hidden" name="action" value="reset_passkey">
            
            <label for="new_passkey">New Passkey</label>
            <div class="password-wrapper">
                <input type="password" name="new_passkey" id="new_passkey" placeholder="Min 4 characters" required>
                <button type="button" class="password-toggle" onclick="togglePassword('new_passkey', this)">Show</button>
            </div>
            
            <label for="confirm_passkey">Confirm Passkey</label>
            <div class="password-wrapper">
                <input type="password" name="confirm_passkey" id="confirm_passkey" placeholder="Confirm your new passkey" required>
                <button type="button" class="password-toggle" onclick="togglePassword('confirm_passkey', this)">Show</button>
            </div>
            
            <button type="submit" class="btn">Update Passkey</button>
        </form>
        
        <div class="back-link">
            <a href="forgot_passkey.php?cancel=1&source=<?= htmlspecialchars($source) ?>">Cancel</a>
        </div>

    <?php endif; ?>

    <div class="footer">Secure your account</div>
</div>

<!-- Success Modal -->
<div class="modal-overlay <?= $reset_complete ? 'active' : '' ?>" id="successModal">
    <div class="modal-content">
        <div class="icon">✅</div>
        <h2>Passkey Updated!</h2>
        <p>Your passkey has been successfully reset. You can now log in to your account with your new passkey.</p>
        <button class="btn" onclick="closeSuccessModal()">Return to <?= ($source === 'dashboard') ? 'Dashboard' : 'Login' ?></button>
    </div>
</div>

<script>
    // ==================== PREVENT SCROLLING AND PULL-TO-REFRESH ====================
    document.addEventListener('DOMContentLoaded', function() {
        // Prevent touchmove on body
        document.body.addEventListener('touchmove', function(e) {
            if (!e.target.closest('.container')) {
                e.preventDefault();
            }
        }, { passive: false });
        
        // Prevent pull-to-refresh
        document.addEventListener('touchstart', function(e) {
            const scrollable = e.target.closest('.container');
            if (!scrollable) {
                // Allow only if touching the container
            }
        }, { passive: true });
        
        // Disable back gesture on iOS
        document.addEventListener('touchstart', function(e) {
            if (e.touches.length === 1) {
                const touchX = e.touches[0].clientX;
                if (touchX < 20) {
                    e.preventDefault();
                }
            }
        }, { passive: false });
    });

    // ==================== CODE INPUT AUTO-ADVANCE ====================
    document.addEventListener('DOMContentLoaded', function() {
        const codeInputs = document.querySelectorAll('.code-input');
        const hiddenInput = document.getElementById('resetCodeHidden');
        const verifyBtn = document.getElementById('verifyBtn');
        
        if (codeInputs.length > 0) {
            // Focus first input on load
            setTimeout(function() {
                if (codeInputs[0] && !codeInputs[0].disabled) {
                    codeInputs[0].focus();
                }
            }, 100);
            
            codeInputs.forEach((input, index) => {
                // Force numeric keyboard
                input.setAttribute('inputmode', 'numeric');
                input.setAttribute('pattern', '[0-9]');
                
                input.addEventListener('input', function(e) {
                    // Allow only digits
                    this.value = this.value.replace(/\D/g, '');
                    
                    // Auto-advance to next input
                    if (this.value.length === 1 && index < codeInputs.length - 1) {
                        codeInputs[index + 1].focus();
                    }
                    
                    // Update hidden input with complete code
                    updateHiddenCode();
                });
                
                input.addEventListener('keydown', function(e) {
                    // Backspace goes to previous
                    if (e.key === 'Backspace' && this.value === '' && index > 0) {
                        codeInputs[index - 1].focus();
                        codeInputs[index - 1].value = '';
                        updateHiddenCode();
                    }
                    
                    // Left arrow goes to previous
                    if (e.key === 'ArrowLeft' && index > 0) {
                        e.preventDefault();
                        codeInputs[index - 1].focus();
                    }
                    
                    // Right arrow goes to next
                    if (e.key === 'ArrowRight' && index < codeInputs.length - 1) {
                        e.preventDefault();
                        codeInputs[index + 1].focus();
                    }
                    
                    // Enter key submits the form
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        let allFilled = true;
                        codeInputs.forEach(inp => {
                            if (inp.value === '') allFilled = false;
                        });
                        if (allFilled && verifyBtn && !verifyBtn.disabled) {
                            document.getElementById('verifyForm').submit();
                        }
                    }
                });
                
                // Allow paste
                input.addEventListener('paste', function(e) {
                    e.preventDefault();
                    const paste = (e.clipboardData || window.clipboardData).getData('text');
                    const digits = paste.replace(/\D/g, '').slice(0, 6);
                    const digitArray = digits.split('');
                    
                    digitArray.forEach((digit, i) => {
                        if (i < codeInputs.length) {
                            codeInputs[i].value = digit;
                        }
                    });
                    
                    // Focus on the next empty input or the last one
                    let nextIndex = Math.min(digitArray.length, codeInputs.length - 1);
                    if (nextIndex < codeInputs.length) {
                        codeInputs[nextIndex].focus();
                    }
                    
                    updateHiddenCode();
                });
                
                // Handle focus to select all text
                input.addEventListener('focus', function() {
                    this.select();
                });
            });
        }
        
        function updateHiddenCode() {
            if (hiddenInput) {
                let code = '';
                codeInputs.forEach(input => {
                    code += input.value;
                });
                hiddenInput.value = code;
            }
        }
    });

    // ==================== PASSWORD TOGGLE ====================
    function togglePassword(inputId, button) {
        const input = document.getElementById(inputId);
        if (input.type === 'password') {
            input.type = 'text';
            button.textContent = 'Hide';
        } else {
            input.type = 'password';
            button.textContent = 'Show';
        }
    }

    // ==================== SUCCESS MODAL ====================
    function closeSuccessModal() {
        document.getElementById('successModal').classList.remove('active');
        <?php if ($source === 'dashboard'): ?>
            window.location.href = 'mydashboard.php';
        <?php else: ?>
            window.location.href = 'index.php';
        <?php endif; ?>
    }

    // Auto-close modal after 5 seconds
    document.addEventListener('DOMContentLoaded', function() {
        const modal = document.getElementById('successModal');
        if (modal.classList.contains('active')) {
            setTimeout(function() {
                closeSuccessModal();
            }, 5000);
        }
    });

    // Close modal on overlay click
    document.addEventListener('DOMContentLoaded', function() {
        const modal = document.getElementById('successModal');
        if (modal) {
            modal.addEventListener('click', function(e) {
                if (e.target === this) {
                    closeSuccessModal();
                }
            });
        }
    });
</script>

</body>
</html>