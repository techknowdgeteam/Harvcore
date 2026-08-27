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
require_once 'PHPMailer/src/PHPMailer.php';
require_once 'PHPMailer/src/SMTP.php';
require_once 'PHPMailer/src/Exception.php';

function sendOTPEmail($email, $code) {
    $mail = new PHPMailer\PHPMailer\PHPMailer(true);
    
    try {
        $mail->isSMTP();
        $mail->Host       = 'smtp.gmail.com';
        $mail->SMTPAuth   = true;
        $mail->Username   = 'techknowdgeteam@gmail.com';
        $mail->Password   = 'rqcrossbioujepda';
        $mail->SMTPSecure = PHPMailer\PHPMailer\PHPMailer::ENCRYPTION_STARTTLS;
        $mail->Port       = 587;
        
        $mail->setFrom('techknowdgeteam@gmail.com', 'HarvHub Support');
        $mail->addAddress($email);
        
        $mail->isHTML(true);
        $mail->Subject = 'Verify Your Email - HarvHub';
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
                    <h3 style='text-align:center;'>Email Verification</h3>
                    <p>Thank you for creating an account with HarvHub. Please verify your email address by entering the following code:</p>
                    <div class='code'>$code</div>
                    <div class='footer'>HarvHub Security</div>
                </div>
            </body>
            </html>
        ";
        $mail->AltBody = "Your email verification code is: $code\n\nHarvHub Security";
        
        $mail->send();
        return true;
    } catch (Exception $e) {
        error_log("Mail Error: " . $mail->ErrorInfo);
        return false;
    }
}

function generateOTP() {
    return str_pad(rand(0, 999999), 6, '0', STR_PAD_LEFT);
}

function storeOTP($pdo, $email, $code) {
    // Delete any existing OTPs for this email
    $stmt = $pdo->prepare("DELETE FROM email_verifications WHERE email = ?");
    $stmt->execute([$email]);
    
    // Insert new OTP (no expiration)
    $stmt = $pdo->prepare("INSERT INTO email_verifications (email, otp_code) VALUES (?, ?)");
    return $stmt->execute([$email, $code]);
}

function verifyOTP($pdo, $email, $code) {
    $stmt = $pdo->prepare("
        SELECT id, otp_code, verified 
        FROM email_verifications 
        WHERE email = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    ");
    $stmt->execute([$email]);
    $record = $stmt->fetch(PDO::FETCH_ASSOC);
    
    if (!$record) {
        return ['valid' => false, 'message' => 'No verification request found. Please request a new code.'];
    }
    
    if ($record['verified'] == 1) {
        return ['valid' => false, 'message' => 'This email has already been verified.'];
    }
    
    if ($record['otp_code'] !== $code) {
        return ['valid' => false, 'message' => 'Invalid verification code. Please try again.'];
    }
    
    return ['valid' => true, 'message' => 'Email verified successfully!'];
}

function markEmailVerified($pdo, $email) {
    $stmt = $pdo->prepare("UPDATE email_verifications SET verified = 1 WHERE email = ? ORDER BY created_at DESC LIMIT 1");
    return $stmt->execute([$email]);
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

// ==================== GET SESSION DATA ====================
$email = $_SESSION['pending_verification_email'] ?? '';
$step = $_SESSION['otp_step'] ?? 'request';
$error = $_SESSION['otp_error'] ?? '';
$success = $_SESSION['otp_success'] ?? '';
$return_to = $_SESSION['return_after_verify'] ?? 'index.php';

// ==================== HANDLE REQUEST OTP ====================
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'request_otp') {
    $email = trim(strtolower($_POST['email'] ?? ''));
    
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $_SESSION['otp_error'] = 'Please enter a valid email address.';
        header('Location: verify_email.php');
        exit;
    }
    
    // Check if user already exists
    $stmt = $pdo->prepare("SELECT id, email_verified FROM insiders WHERE email = ? LIMIT 1");
    $stmt->execute([$email]);
    $user = $stmt->fetch(PDO::FETCH_ASSOC);
    
    if ($user && $user['email_verified'] == 1) {
        $_SESSION['otp_error'] = 'This email is already verified. Please login.';
        header('Location: verify_email.php');
        exit;
    }
    
    // Generate and store OTP
    $code = generateOTP();
    $maskedEmail = maskEmail($email);
    
    if (!storeOTP($pdo, $email, $code)) {
        $_SESSION['otp_error'] = 'Failed to generate verification code. Please try again.';
        header('Location: verify_email.php');
        exit;
    }
    
    // Send email
    if (sendOTPEmail($email, $code)) {
        $_SESSION['pending_verification_email'] = $email;
        $_SESSION['otp_step'] = 'verify';
        $_SESSION['otp_success'] = "A verification code has been sent to {$maskedEmail}.";
        unset($_SESSION['otp_error']);
    } else {
        $_SESSION['otp_error'] = 'Failed to send verification email. Please try again or contact support.';
    }
    
    header('Location: verify_email.php');
    exit;
}

// ==================== HANDLE VERIFY OTP ====================
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'verify_otp') {
    $code = trim($_POST['otp_code'] ?? '');
    $email = $_SESSION['pending_verification_email'] ?? '';
    
    if (empty($email)) {
        $_SESSION['otp_error'] = 'Session expired. Please start over.';
        $_SESSION['otp_step'] = 'request';
        unset($_SESSION['pending_verification_email']);
        header('Location: verify_email.php');
        exit;
    }
    
    if (empty($code) || strlen($code) !== 6) {
        $_SESSION['otp_error'] = 'Please enter the complete 6-digit verification code.';
        header('Location: verify_email.php');
        exit;
    }
    
    $result = verifyOTP($pdo, $email, $code);
    
    if ($result['valid']) {
        // Mark email as verified in the verification table
        markEmailVerified($pdo, $email);
        
        // ==================== CREATE/UPDATE USER ACCOUNT ====================
        $hashed_passkey = $_SESSION['pending_verification_passkey'] ?? '';
        
        // Check if user already exists
        $stmt = $pdo->prepare("SELECT id, email_verified FROM insiders WHERE email = ? LIMIT 1");
        $stmt->execute([$email]);
        $existing = $stmt->fetch();
        
        if ($existing) {
            // User exists - update them
            if (!empty($hashed_passkey)) {
                $stmt = $pdo->prepare("UPDATE insiders SET passkey = ?, email_verified = 1 WHERE email = ?");
                $stmt->execute([$hashed_passkey, $email]);
            } else {
                $stmt = $pdo->prepare("UPDATE insiders SET email_verified = 1 WHERE email = ?");
                $stmt->execute([$email]);
            }
        } else {
            // New user - create account
            if (!empty($hashed_passkey)) {
                $stmt = $pdo->prepare("INSERT INTO insiders (email, passkey, email_verified) VALUES (?, ?, 1)");
                $stmt->execute([$email, $hashed_passkey]);
            }
        }
        
        $_SESSION['otp_step'] = 'success';
        $_SESSION['otp_success'] = $result['message'];
        unset($_SESSION['otp_error']);
        
        // Store in session that email is verified
        $_SESSION['email_verified'] = true;
        $_SESSION['user_email'] = $email;
        
        // Clear signup temp data
        unset($_SESSION['pending_verification_passkey']);
        unset($_SESSION['signup_in_progress']);
        
    } else {
        $_SESSION['otp_error'] = $result['message'];
    }
    
    header('Location: verify_email.php');
    exit;
}

// ==================== HANDLE RESEND OTP ====================
if (isset($_GET['resend']) && $_GET['resend'] === '1') {
    $email = $_SESSION['pending_verification_email'] ?? '';
    
    if (!empty($email)) {
        $code = generateOTP();
        $maskedEmail = maskEmail($email);
        
        if (storeOTP($pdo, $email, $code)) {
            if (sendOTPEmail($email, $code)) {
                $_SESSION['otp_success'] = "A new verification code has been sent to {$maskedEmail}.";
                unset($_SESSION['otp_error']);
            } else {
                $_SESSION['otp_error'] = 'Failed to send email. Please try again.';
            }
        } else {
            $_SESSION['otp_error'] = 'Failed to generate new code. Please try again.';
        }
    }
    
    header('Location: verify_email.php');
    exit;
}

// ==================== HANDLE CANCEL ====================
if (isset($_GET['cancel'])) {
    // Check if this was an approved user
    $is_approved = $_SESSION['is_approved_user'] ?? false;
    
    // Clear all verification session variables
    unset($_SESSION['pending_verification_email']);
    unset($_SESSION['otp_step']);
    unset($_SESSION['otp_success']);
    unset($_SESSION['otp_error']);
    unset($_SESSION['email_verified']);
    unset($_SESSION['is_approved_user']);
    unset($_SESSION['return_after_verify']);
    
    // For approved users, just go back to dashboard (they're still logged in)
    // For others, logout completely
    if ($is_approved) {
        header('Location: mydashboard.php');
    } else {
        unset($_SESSION['user_email']);
        session_destroy();
        header('Location: index.php');
    }
    exit;
}

// ==================== HANDLE CONTINUE ====================
if (isset($_GET['continue'])) {
    if (isset($_SESSION['email_verified']) && $_SESSION['email_verified'] === true) {
        // User is verified, check where to redirect
        $return_to = $_SESSION['return_after_verify'] ?? 'index.php';
        $is_approved = $_SESSION['is_approved_user'] ?? false;
        
        // Clear verification sessions
        unset($_SESSION['pending_verification_email']);
        unset($_SESSION['otp_step']);
        unset($_SESSION['otp_success']);
        unset($_SESSION['otp_error']);
        unset($_SESSION['is_approved_user']);
        unset($_SESSION['return_after_verify']);
        
        // If approved user, go to dashboard, otherwise go to index
        if ($is_approved && $return_to === 'mydashboard.php') {
            header('Location: mydashboard.php');
        } else {
            header('Location: ' . $return_to);
        }
        exit;
    }
    // If not verified, stay on verify page
    header('Location: verify_email.php');
    exit;
}

// ==================== GET CURRENT STATE ====================
$email = $_SESSION['pending_verification_email'] ?? '';
$step = $_SESSION['otp_step'] ?? 'request';
$error = $_SESSION['otp_error'] ?? '';
$success = $_SESSION['otp_success'] ?? '';
$maskedEmail = !empty($email) ? maskEmail($email) : '';

// Clear error/success after display
unset($_SESSION['otp_error']);
unset($_SESSION['otp_success']);
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Verify Email - HarvHub</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    /* ==================== CSS VARIABLES ==================== */
    :root {
        --bg-primary: #000;
        --bg-secondary: rgba(20, 20, 30, 0.95);
        --bg-input: #1a1a2e;
        --bg-success-details: rgba(46, 139, 87, 0.1);
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
        --badge-bg: rgba(46, 139, 87, 0.2);
        --btn-text: #000;
        --scrollbar-track: #1a1a2e;
        --scrollbar-thumb: #2e8b57;
        --scrollbar-thumb-hover: #3a9b67;
        --dot-color: white;
    }

    /* ==================== LIGHT MODE OVERRIDES ==================== */
    @media (prefers-color-scheme: light) {
        :root {
            --bg-primary: #f0f2f5;
            --bg-secondary: rgba(255, 255, 255, 0.95);
            --bg-input: #ffffff;
            --bg-success-details: rgba(46, 139, 87, 0.08);
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
            --badge-bg: rgba(46, 139, 87, 0.15);
            --btn-text: #fff;
            --scrollbar-track: #e8e8e8;
            --scrollbar-thumb: #2e8b57;
            --scrollbar-thumb-hover: #3a9b67;
            --dot-color: #666;
        }
        
        /* Light mode specific overrides */
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
        
        .description {
            color: #555;
        }
        
        .email-display {
            background: rgba(46, 139, 87, 0.05);
            color: #2e8b57;
        }
        
        .status-badge {
            background: rgba(46, 139, 87, 0.15);
            color: #2e8b57;
        }
        
        .success-details {
            background: rgba(46, 139, 87, 0.08);
        }
        
        .success-details p {
            color: #555;
        }
        
        .success-details strong {
            color: #2e8b57;
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
        
        .success-details {
            background: rgba(46, 139, 87, 0.1);
        }
        
        .success-details p {
            color: #aaa;
        }
        
        .success-details strong {
            color: #2e8b57;
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
            url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><circle cx="10" cy="10" r="1" fill="%23' + (window.matchMedia('(prefers-color-scheme: light)').matches ? '999' : 'fff') + '"/><circle cx="30" cy="70" r="1.5" fill="%23' + (window.matchMedia('(prefers-color-scheme: light)').matches ? '999' : 'fff') + '"/><circle cx="70" cy="30" r="1" fill="%23' + (window.matchMedia('(prefers-color-scheme: light)').matches ? '999' : 'fff') + '"/><circle cx="90" cy="80" r="1.2" fill="%23' + (window.matchMedia('(prefers-color-scheme: light)').matches ? '999' : 'fff') + '"/><circle cx="50" cy="50" r="1.8" fill="%23' + (window.matchMedia('(prefers-color-scheme: light)').matches ? '999' : 'fff') + '"/></svg>') repeat;
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
    
    .success-icon {
        font-size: 4rem;
        text-align: center;
        margin: 10px 0;
    }
    
    .success-details {
        border-radius: 12px;
        padding: 15px;
        margin: 15px 0;
        transition: background 0.3s ease;
    }
    
    .success-details p {
        margin: 5px 0;
        transition: color 0.3s ease;
    }
    
    .success-details strong {
        transition: color 0.3s ease;
    }
    
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.7rem;
        margin-bottom: 15px;
        text-align: center;
        width: 100%;
        transition: background 0.3s ease, color 0.3s ease;
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
        .success-icon {
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
        <!-- STEP 1: Request OTP -->
        <h2>Verify Your Email</h2>
        <p class="description">We'll send a verification code to <strong><?= htmlspecialchars($maskedEmail) ?></strong> to verify your email.</p>
        
        <?php if (!empty($error)): ?>
            <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>
        
        <form method="POST" action="verify_email.php">
            <input type="hidden" name="action" value="request_otp">
            
            <label for="email" style="display: none;">Email Address</label>
            <input type="email" name="email" id="email" placeholder="youremail@gmail.com" value="<?= htmlspecialchars($email) ?>" required autofocus style="display: none;">
            <button type="submit" class="btn">Send Verification Code</button>
        </form>
        
        <div class="back-link">
            <a href="?cancel=1">Cancel &amp; Return</a>
        </div>

    <?php elseif ($step === 'verify'): ?>
        <!-- STEP 2: Verify OTP -->
        <h2>Enter Verification Code</h2>
        <p class="success-message">We sent a 6-digit verification code to <?= htmlspecialchars($maskedEmail) ?></p>
        <?php if (!empty($error)): ?>
            <div class="error-message"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>
        
        <form method="POST" action="verify_email.php" id="verifyForm">
            <input type="hidden" name="action" value="verify_otp">
            <label>Enter 6-Digit Code</label>
            <div class="code-input-container" id="codeContainer">
                <input type="text" maxlength="1" class="code-input" data-index="0" autofocus required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="1" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="2" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="3" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="4" required inputmode="numeric" pattern="[0-9]">
                <input type="text" maxlength="1" class="code-input" data-index="5" required inputmode="numeric" pattern="[0-9]">
            </div>
            <input type="hidden" name="otp_code" id="otpCodeHidden" value="">
            
            <button type="submit" class="btn" id="verifyBtn">Verify Email</button>
        </form>
        
        <div class="resend-link">
            <a href="?resend=1" id="resendLink">Resend Code</a> &nbsp;|&nbsp;
            <a href="?cancel=1">Cancel</a>
        </div>

    <?php elseif ($step === 'success'): ?>
        <!-- STEP 3: Success -->
        <div class="success-icon">✅</div>
        <h2>Email Verified!</h2>
        <p class="description">Your email has been successfully verified. You can now proceed to complete your registration.</p>
        
        <div class="success-details">
            <p><strong>Email:</strong> <?= htmlspecialchars($email) ?></p>
            <p><strong>Status:</strong> <span style="color: #2e8b57;">Verified ✓</span></p>
        </div>
        
        <button class="btn" onclick="window.location.href='?continue=1'">Continue to Registration</button>
        
        <div class="back-link">
            <a href="?cancel=1">Cancel &amp; Return</a>
        </div>
    <?php endif; ?>

    <div class="footer">Secure your account</div>
</div>

<script>
    // ==================== PREVENT SCROLLING AND PULL-TO-REFRESH ====================
    document.addEventListener('DOMContentLoaded', function() {
        document.body.addEventListener('touchmove', function(e) {
            if (!e.target.closest('.container')) {
                e.preventDefault();
            }
        }, { passive: false });
    });

    // ==================== CODE INPUT AUTO-ADVANCE ====================
    document.addEventListener('DOMContentLoaded', function() {
        const codeInputs = document.querySelectorAll('.code-input');
        const hiddenInput = document.getElementById('otpCodeHidden');
        const verifyBtn = document.getElementById('verifyBtn');
        
        if (codeInputs.length > 0) {
            setTimeout(function() {
                if (codeInputs[0] && !codeInputs[0].disabled) {
                    codeInputs[0].focus();
                }
            }, 100);
            
            codeInputs.forEach((input, index) => {
                input.setAttribute('inputmode', 'numeric');
                input.setAttribute('pattern', '[0-9]');
                
                input.addEventListener('input', function(e) {
                    this.value = this.value.replace(/\D/g, '');
                    
                    if (this.value.length === 1 && index < codeInputs.length - 1) {
                        codeInputs[index + 1].focus();
                    }
                    
                    updateHiddenCode();
                });
                
                input.addEventListener('keydown', function(e) {
                    if (e.key === 'Backspace' && this.value === '' && index > 0) {
                        codeInputs[index - 1].focus();
                        codeInputs[index - 1].value = '';
                        updateHiddenCode();
                    }
                    
                    if (e.key === 'ArrowLeft' && index > 0) {
                        e.preventDefault();
                        codeInputs[index - 1].focus();
                    }
                    
                    if (e.key === 'ArrowRight' && index < codeInputs.length - 1) {
                        e.preventDefault();
                        codeInputs[index + 1].focus();
                    }
                    
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
                    
                    let nextIndex = Math.min(digitArray.length, codeInputs.length - 1);
                    if (nextIndex < codeInputs.length) {
                        codeInputs[nextIndex].focus();
                    }
                    
                    updateHiddenCode();
                });
                
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

    // ==================== AUTO-REDIRECT AFTER SUCCESS ====================
    <?php if ($step === 'success'): ?>
    setTimeout(function() {
        window.location.href = '?continue=1';
    }, 5000);
    <?php endif; ?>
</script>

</body>
</html>