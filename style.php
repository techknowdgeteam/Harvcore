<style>
    /* ===== ROOT VARIABLES - Complete Light/Dark Support ===== */
    :root {
        /* Light mode defaults */
        --bg: #ffffff;
        --bg-secondary: #f8f9fa;
        --text: #1c1e21;
        --text-secondary: #4a4a4a;
        --text-muted: #6c757d;
        --text-light: #1e293b;
        --accent: #10b981;
        --accent-hover: #059669;
        --danger: #ef4444;
        --warning: #f59e0b;
        --info: #3b82f6;
        --success: #10b981;
        --info-color: #3b82f6;
        --success-color: #10b981;
        --error-color: #dc2626;
        --warning-color: #f59e0b;
        --border-color: #d1d5db;
        
        /* Input specific */
        --input-bg: #f0f2f5;
        --input-border: #d1d5db;
        --input-text: #1c1e21;
        --input-placeholder: #9ca3af;
        
        /* Card & Section */
        --section-bg: #ffffff;
        --section-shadow: 0 4px 12px rgba(0,0,0,0.08);
        --card-light: rgba(255, 255, 255, 0.95);
        --card-dark: rgba(30, 41, 59, 0.95);
        --glass-border: rgba(0, 0, 0, 0.1);
        
        /* Shadows */
        --shadow-sm: 0 10px 40px rgba(0, 0, 0, 0.1);
        --shadow-lg: 0 20px 60px rgba(0, 0, 0, 0.15);
        --shadow-hover: 0 30px 70px rgba(16, 185, 129, 0.2);
        
        /* Modal specific */
        --modal-overlay: rgba(0, 0, 0, 0.5);
        --modal-bg: #ffffff;
        --modal-text: #1c1e21;
        
        /* Passkey modal */
        --passkey-bg: rgba(255, 255, 255, 0.95);
        --passkey-text: #1c1e21;
        
        /* Split items */
        --split-bg: rgba(0, 0, 0, 0.05);
        --split-text: #1c1e21;
        
        /* Crypto details */
        --crypto-details-bg: rgba(0, 0, 0, 0.05);
        
        /* Disconnect warning */
        --disconnect-warning-bg: rgba(220, 38, 38, 0.08);
        
        /* Checkbox */
        --checkbox-bg: rgba(0, 0, 0, 0.05);
        
        /* Re-enrollment */
        --reenroll-bg: rgba(0, 0, 0, 0.05);
        --consequence-bg: rgba(220, 38, 38, 0.08);
        
        /* Notifications */
        --notification-item-bg: rgba(0, 0, 0, 0.03);
        --notification-unread-bg: rgba(59, 130, 246, 0.08);
        
        /* Revenue */
        --revenue-header-bg: rgba(0, 0, 0, 0.03);
        --revenue-details-bg: rgba(0, 0, 0, 0.05);
        --revenue-border: rgba(0, 0, 0, 0.05);
        --address-bg: rgba(0, 0, 0, 0.05);
        --history-bg: rgba(0, 0, 0, 0.05);
        --history-border: rgba(0, 0, 0, 0.08);
        
        /* Text colors for specific elements */
        --text-color: #1c1e21;
        --profile-text: #1c1e21;
        --profile-details-text: #1c1e21;
    }

    /* ===== DARK MODE OVERRIDES ===== */
    @media (prefers-color-scheme: dark) {
        :root {
            --bg: #000000;
            --bg-secondary: #111827;
            --text: #e4e6eb;
            --text-secondary: #b0b8c8;
            --text-muted: #8b95a9;
            --text-light: #f1f5f9;
            --input-bg: #1a1a1a;
            --input-border: #374151;
            --input-text: #e4e6eb;
            --input-placeholder: #6b7280;
            --section-bg: rgba(255,255,255,0.05);
            --section-shadow: none;
            --card-light: rgba(37, 52, 77, 0.6);
            --card-dark: rgba(30, 41, 59, 0.95);
            --glass-border: rgba(255, 255, 255, 0.1);
            --shadow-sm: 0 10px 40px rgba(0, 0, 0, 0.3);
            --shadow-lg: 0 20px 60px rgba(0, 0, 0, 0.4);
            --shadow-hover: 0 30px 70px rgba(16, 185, 129, 0.15);
            --modal-overlay: rgba(0, 0, 0, 0.85);
            --modal-bg: #1a1a2e;
            --modal-text: #e4e6eb;
            --passkey-bg: rgba(40, 40, 40, 0.95);
            --passkey-text: #e4e6eb;
            --error-color: #ff6b6b;
            --split-bg: rgba(255, 255, 255, 0.05);
            --split-text: #e4e6eb;
            --crypto-details-bg: rgba(255, 255, 255, 0.05);
            --disconnect-warning-bg: rgba(255, 107, 107, 0.08);
            --checkbox-bg: rgba(255, 255, 255, 0.05);
            --reenroll-bg: rgba(255, 255, 255, 0.05);
            --consequence-bg: rgba(255, 107, 107, 0.08);
            --notification-item-bg: rgba(255, 255, 255, 0.03);
            --notification-unread-bg: rgba(59, 130, 246, 0.15);
            --revenue-header-bg: rgba(255, 255, 255, 0.03);
            --revenue-details-bg: rgba(255, 255, 255, 0.05);
            --revenue-border: rgba(255, 255, 255, 0.05);
            --address-bg: rgba(255, 255, 255, 0.05);
            --history-bg: rgba(255, 255, 255, 0.05);
            --history-border: rgba(255, 255, 255, 0.08);
            --text-color: #e4e6eb;
            --profile-text: #e4e6eb;
            --profile-details-text: #e4e6eb;
        }
    }

    /* ===== BASE RESET ===== */
    * { margin:0; padding:0; box-sizing:border-box; }
    
    body {
        font-family: 'Segoe UI', sans-serif;
        background: var(--bg);
        color: var(--text);
        height: 100vh;
        overflow: hidden;
        position: relative;
    }

    html, body { 
        -ms-overflow-style: none; 
        scrollbar-width: none; 
    }
    html::-webkit-scrollbar, body::-webkit-scrollbar { 
        display: none; 
    }

    /* ===== SCROLLABLE CONTAINERS ===== */
    .container, .modal-content, .custom-body {
        overflow-y: auto; 
        -ms-overflow-style: none; 
        scrollbar-width: none; 
    }
    .container::-webkit-scrollbar, 
    .modal-content::-webkit-scrollbar, 
    .custom-body::-webkit-scrollbar { 
        display: none; 
    }

    .custom-body {
        width: 100%;
        height: 100%;
        background: var(--bg-secondary);
        overflow-y: auto;
        -ms-overflow-style: none;
        scrollbar-width: none;
    }
    .custom-body::-webkit-scrollbar {
        display: none;
    }
</style>
<style>


    /* ===== PASSKEY MODAL ===== */
    .passkey-overlay {
        position: fixed;
        inset: 0;
        background: var(--modal-overlay);
        backdrop-filter: blur(8px);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
        padding: 1rem;
    }

    .passkey-screen {
        background: var(--passkey-bg);
        color: var(--passkey-text);
        backdrop-filter: blur(12px);
        padding: 3rem 2.5rem;
        border-radius: 20px;
        width: 100%;
        max-width: 480px;
        text-align: center;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        border: 1px solid var(--glass-border);
    }

    .passkey-screen h2 {
        font-size: 2rem;
        margin-bottom: 1rem;
        color: var(--passkey-text);
        background: none;
        -webkit-text-fill-color: var(--passkey-text);
    }

    .passkey-screen p {
        margin: 1.5rem 0;
        opacity: 0.9;
        font-size: 1rem;
        color: var(--passkey-text);
    }

    .passkey-screen input[type="password"] {
        width: 100%;
        padding: 16px;
        margin: 20px 0;
        border: 1px solid var(--input-border);
        border-radius: 12px;
        font-size: 1.1rem;
        text-align: center;
        background: var(--input-bg);
        color: var(--input-text);
    }

    .passkey-screen input[type="password"]::placeholder {
        color: var(--input-placeholder);
    }

    .passkey-screen .error-message { 
        color: var(--error-color); 
        margin: -10px 0 10px; 
        font-weight: bold; 
    }

    .passkey-screen .btn-full {
        width: 100%;
        padding: 16px;
        background: var(--accent);
        color: #000;
        border: none;
        border-radius: 12px;
        font-weight: bold;
        font-size: 1.1rem;
        cursor: pointer;
        transition: opacity 0.3s;
    }

    .passkey-screen .btn-full:hover {
        opacity: 0.9;
    }

    .passkey-screen a {
        display: block;
        margin: 20px 0;
        color: var(--accent);
        font-size: 0.95rem;
        text-decoration: none;
    }

    .passkey-screen a:hover {
        text-decoration: underline;
    }

    .passkey-screen a[href*="logout"] {
        color: var(--danger);
    }

    /* ===== DASHBOARD ===== */
    .dashboard-wrapper {
        width: 100%;
        max-width: 1300px;
        height: 100vh;
        margin: 0 auto;
        padding: 2rem;
        overflow-y: auto;
        scroll-behavior: smooth;
        -ms-overflow-style: none;
        scrollbar-width: none;
        position: relative;
    }
    .dashboard-wrapper::-webkit-scrollbar {
        display: none;
    }

    h1 {
        font-size: 3.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, var(--accent) 0%, var(--info) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-align: center;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
        animation: fadeInDown 0.6s ease;
    }

    .welcome {
        text-align: center;
        font-size: 1.25rem;
        margin-bottom: 2rem;
        opacity: 0.9;
        animation: fadeInUp 0.6s ease 0.2s both;
        color: var(--text);
    }

    .welcome strong {
        background: linear-gradient(135deg, var(--accent), var(--info));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 1.5rem;
        margin: 2rem 0;
        animation: fadeInUp 0.6s ease 0.4s both;
    }

    @media (max-width: 768px) {
        .stats-grid {
            grid-template-columns: 1fr;
        }
        h1 {
            font-size: 2.5rem;
        }
        .dashboard-wrapper {
            padding: 1rem;
        }
    }

    /* ===== STAT CARDS ===== */
    .stat-card {
        position: relative;
        background: var(--card-light);
        backdrop-filter: blur(20px);
        padding: 1.75rem;
        border-radius: 24px;
        text-align: center;
        border: 1px solid var(--glass-border);
        box-shadow: var(--shadow-sm);
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        overflow: hidden;
        animation: cardAppear 0.5s ease;
        color: var(--text);
    }

    .stat-card:hover {
        transform: translateY(-10px) scale(1.02);
    }

    .stat-card h3 {
        font-size: 1.1rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        opacity: 0.7;
        margin-bottom: 1rem;
        color: var(--text-secondary);
    }

    .stat-card h2 {
        font-size: 2.8rem;
        font-weight: 800;
        line-height: 1.2;
        margin: 0.5rem 0;
        transition: all 0.3s ease;
        position: relative;
        display: inline-block;
        color: var(--text);
    }

    .stat-card h2::after {
        content: '';
        position: absolute;
        bottom: -5px;
        left: 50%;
        transform: translateX(-50%);
        width: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--accent), var(--info));
        transition: width 0.3s ease;
        border-radius: 2px;
    }

    .stat-card:hover h2::after {
        width: 50%;
    }

    .stat-details-info {
        font-size: 0.9rem;
        opacity: 0.6;
        padding: 0.5rem;
        transition: all 0.3s ease;
        color: var(--text-secondary);
    }

    .stat-card:hover .stat-details-info {
        opacity: 0.9;
    }

    /* ===== BALANCE TOGGLE ===== */
    .balance-toggle-btn {
        position: absolute;
        top: 15px;
        right: 15px;
        background: rgba(0, 0, 0, 0.05);
        border: 1px solid var(--glass-border);
        color: var(--text);
        font-size: 1.25rem;
        cursor: pointer;
        padding: 8px;
        border-radius: 12px;
        opacity: 0.6;
        transition: all 0.3s ease;
        backdrop-filter: blur(10px);
        z-index: 10;
    }

    .balance-toggle-btn:hover {
        opacity: 1;
        background: var(--accent);
        color: white;
        transform: rotate(15deg);
    }

    /* ===== PROFIT/LOSS COLORS ===== */
    .profit-positive {
        color: var(--success) !important;
        text-shadow: 0 0 20px rgba(16, 185, 129, 0.3);
    }

    .profit-negative {
        color: var(--danger) !important;
        text-shadow: 0 0 20px rgba(239, 68, 68, 0.3);
    }

    /* ===== LOYALTY CARD ===== */
    .stat-card.loyalty-card {
        grid-column: 1 / -1;
        max-width: 800px;
        margin: 2rem auto;
        background: var(--card-light);
        color: var(--text);
    }

    .loyalty-status-msg {
        font-size: 1.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, var(--accent), var(--info));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .loyalty-card p {
        font-size: 1.1rem;
        line-height: 1.6;
        opacity: 0.9;
        max-width: 600px;
        margin: 0 auto 1rem;
        color: var(--text);
    }

    .contract-dates {
        display: inline-block;
        padding: 0.5rem 1.5rem;
        background: rgba(0, 0, 0, 0.05);
        border-radius: 50px;
        font-size: 0.9rem;
        font-weight: 500;
        margin: 0.5rem;
        backdrop-filter: blur(10px);
        color: var(--text);
    }

    .contract-days-left {
        display: inline-block;
        padding: 0.25rem 1rem;
        background: var(--accent);
        color: white;
        border-radius: 50px;
        font-size: 0.9rem;
        font-weight: 600;
        margin-left: 0.5rem;
    }

    .loyalty-card small {
        color: var(--text-muted);
        opacity: 0.6;
    }

    /* ===== LOYALTY BUTTONS ===== */
    .loyalty-card button {
        margin: 1.5rem auto 0;
        padding: 1rem 3rem;
        font-size: 1.1rem;
        font-weight: 700;
        border: none;
        border-radius: 50px;
        cursor: pointer;
        transition: all 0.3s ease;
        text-transform: uppercase;
        letter-spacing: 1px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }

    .btn-loyalty-action {
        background: linear-gradient(135deg, var(--accent), var(--info)) !important;
        color: white !important;
    }

    .btn-loyalty-action:hover {
        transform: translateY(-3px) scale(1.05);
        box-shadow: 0 10px 30px rgba(16, 185, 129, 0.5) !important;
    }

    .btn-loyalty-paid {
        background: linear-gradient(135deg, #6b7280, #4b5563) !important;
        color: white !important;
        cursor: not-allowed !important;
        opacity: 0.7;
    }

    .btn-loyalty-confirmed {
        background: linear-gradient(135deg, var(--success), #059669) !important;
        color: white !important;
        cursor: default !important;
    }

    .btn-loyalty-apply {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px;
        font-weight: bold;
        cursor: pointer;
        transition: all 0.3s ease;
        margin-top: 1rem;
        width: 100%;
    }

    .btn-loyalty-apply:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
    }

    .btn-loyalty-deposit {
        background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px;
        font-weight: bold;
        cursor: pointer;
        transition: all 0.3s ease;
        width: 100%;
    }

    /* ===== STATUS BADGES ===== */
    .balance-status-badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: bold;
        margin-left: 8px;
    }

    .balance-status-unverified {
        background: var(--danger);
        color: white;
    }

    .balance-status-pending {
        background: var(--warning);
        color: white;
    }

    .balance-status-verified {
        background: var(--success);
        color: white;
    }

    /* ===== DISCLAIMER ===== */
    .dashboard-disclaimer {
        text-align: center;
        margin: 1.5rem auto;
        padding: 1rem 2rem;
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(16, 185, 129, 0.15));
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 50px;
        font-weight: 600;
        font-size: 1.1rem;
        max-width: 600px;
        backdrop-filter: blur(10px);
        animation: slideIn 0.5s ease;
        color: var(--text);
    }

    .payment-required-badge {
        background: var(--danger);
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: bold;
        margin-left: 10px;
    }

    .encouragement-note {
        text-align: center;
        margin: 1rem auto;
        padding: 1rem;
        background: rgba(245, 158, 11, 0.1);
        border: 1px solid var(--warning);
        border-radius: 16px;
        font-style: italic;
        font-size: 1.1rem;
        max-width: 800px;
        animation: pulse 2s infinite;
        color: var(--text);
    }

    .threshold-warning {
        background: rgba(255, 193, 7, 0.1);
        border-left: 4px solid var(--warning);
        padding: 12px;
        margin: 10px 0;
        font-size: 0.9rem;
        color: var(--text);
    }

    /* ===== DANGER BUTTON ===== */
    .btn-danger {
        display: block;
        margin-bottom: 10px;
        margin-top: 10px;
        padding: 1rem 1rem;
        background: linear-gradient(135deg, var(--danger), #dc2626);
        color: white;
        border: none;
        border-radius: 20px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.3s ease;
        text-transform: uppercase;
        letter-spacing: 1px;
        box-shadow: 0 4px 15px rgba(239, 68, 68, 0.3);
    }

    .btn-danger:hover {
        transform: translateY(-3px) scale(1.05);
        box-shadow: 0 10px 30px rgba(239, 68, 68, 0.5);
    }

    .note-btndanger {
        display: flex;
        justify-content: center;
        width: 100%;
        margin: 20px 0;
    }

    .note-btndanger-block {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        max-width: 600px;
        width: 100%;
    }

    .logout-link-p {
        margin-top: 20px;
        margin-bottom: 70px;
    }

    .logout-link-p a {
        color: var(--danger);
        text-decoration: none;
        transition: opacity 0.3s;
    }

    .logout-link-p a:hover {
        opacity: 0.8;
    }

    /* ===== BLUR MODE ===== */
    .dashboard-wrapper.blur-mode .stat-card h2 {
        filter: blur(8px);
        transition: filter 0.3s ease;
        user-select: none;
    }

    .dashboard-wrapper.blur-mode .stat-card:hover h2 {
        filter: blur(6px);
    }

    /* ===== REVENUE HISTORY BUTTON ===== */
    .btn-revenue-history {
        background: none;
        color: var(--text-secondary);
        border: none;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        padding: 8px 16px;
        margin-top: 8px;
    }

    .btn-revenue-history:hover {
        color: var(--accent);
        background: rgba(16, 185, 129, 0.1);
    }

    .invested_with-value {
        font-size: 12px;
        color: var(--success);
    }

    .revenue-detail-value.broker-name {
        color: var(--accent);
        font-weight: 500;
    }

    /* ===== MODALS ===== */
    .modal {
        display: none;
        position: fixed;
        inset: 0;
        background: var(--modal-overlay);
        backdrop-filter: blur(10px);
        align-items: center;
        justify-content: center;
        z-index: 999;
        padding: 1rem;
        animation: fadeIn 0.3s ease;
    }

    .modal.active {
        display: flex;
    }

    .modal-content {
        background: var(--modal-bg);
        color: var(--modal-text);
        backdrop-filter: blur(20px);
        padding: 2.5rem;
        border-radius: 24px;
        max-width: 500px;
        width: 90%;
        max-height: 80vh;
        overflow-y: auto;
        border: 1px solid var(--glass-border);
        box-shadow: var(--shadow-lg);
        animation: modalSlideUp 0.4s ease;
    }

    .modal-content h2 {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 1rem;
        color: var(--modal-text);
        background: none;
        -webkit-text-fill-color: var(--modal-text);
    }

    .modal-content p {
        color: var(--modal-text);
        opacity: 0.8;
    }

    .modal-content label {
        color: var(--modal-text);
    }

    .modal-content small {
        color: var(--text-muted);
    }

    .modal-actions {
        display: flex;
        gap: 1rem;
        margin-top: 2rem;
    }

    .modal-actions button {
        flex: 1;
        padding: 0.75rem 1.5rem;
        border: none;
        border-radius: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        color: white;
    }

    .modal-actions button:hover {
        transform: translateY(-2px);
    }

    .modal-actions-vertical {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-top: 1rem;
    }

    /* ===== DISCONNECT MODAL ===== */
    .disconnect-verify-section {
        margin: 1.5rem 0;
        text-align: left;
    }

    .disconnect-verify-section label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: var(--modal-text);
    }

    .disconnect-verify-section input {
        width: 100%;
        padding: 12px;
        border: 1px solid var(--input-border);
        border-radius: 8px;
        background: var(--input-bg);
        color: var(--input-text);
        font-size: 1rem;
        margin-bottom: 1rem;
        box-sizing: border-box;
    }

    .disconnect-verify-section input::placeholder {
        color: var(--input-placeholder);
    }

    .disconnect-verify-section input:focus {
        outline: none;
        border-color: var(--accent);
    }

    .disconnect-warning-note {
        background: var(--disconnect-warning-bg);
        border-left: 3px solid var(--danger);
        padding: 1rem;
        margin: 1.5rem 0;
        border-radius: 8px;
        font-size: 0.9rem;
        color: var(--modal-text);
    }

    .disconnect-warning-note strong {
        color: var(--danger);
    }

    .disconnect-errors {
        background: rgba(220, 38, 38, 0.1);
        border: 1px solid var(--danger);
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 1rem;
    }

    .disconnect-errors ul {
        margin: 0;
        padding-left: 1.25rem;
    }

    .disconnect-errors li {
        color: var(--danger);
        font-size: 0.85rem;
        margin: 0.25rem 0;
    }

    .btn-danger-final {
        background: var(--danger);
        color: white;
        border: none;
        padding: 14px;
        border-radius: 8px;
        font-size: 1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .btn-danger-final:hover {
        background: #dc2626;
        transform: scale(1.02);
    }

    .btn-danger-final:disabled {
        background: #555;
        cursor: not-allowed;
        opacity: 0.6;
        transform: none;
    }

    .btn-cancel-final {
        background: #6b7280;
        color: white;
        border: none;
        padding: 12px;
        border-radius: 8px;
        font-size: 0.95rem;
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .btn-cancel-final:hover {
        background: #7b8290;
    }

    /* ===== SPLIT MODAL ===== */
    .unpaid-warning {
        background: rgba(220, 38, 38, 0.08);
        border-left: 4px solid var(--danger);
        padding: 12px;
        margin: 10px 0;
        font-size: 0.9rem;
        color: var(--modal-text);
    }

    .unpaid-warning strong {
        color: var(--danger);
    }

    .split-container {
        display: flex;
        gap: 1.5rem;
        margin: 1.5rem 0;
    }

    .split-item {
        background: var(--split-bg);
        padding: 1.5rem;
        border-radius: 16px;
        margin: 1rem 0;
        border: 1px solid var(--glass-border);
        transition: all 0.3s ease;
        flex: 1;
        color: var(--split-text);
    }

    .split-item:hover {
        transform: translateY(-3px);
        border-color: var(--accent);
        box-shadow: 0 10px 30px rgba(16, 185, 129, 0.2);
    }

    .split-item h4 {
        font-size: 2rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
        color: var(--split-text);
    }

    .split-item p {
        color: var(--split-text);
        opacity: 0.8;
    }

    .split-total {
        font-size: 1.2rem;
        font-weight: 600;
        text-align: center;
        padding: 0.5rem;
        background: rgba(16, 185, 129, 0.1);
        border-radius: 8px;
        color: var(--modal-text);
    }

    .btn-withdraw {
        background: var(--success);
        color: white;
        padding: 10px 20px;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        margin-top: 10px;
        display: block;
        width: 100%;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .btn-withdraw:hover {
        opacity: 0.85;
        transform: translateY(-2px);
    }

    .btn-pay {
        background: var(--info);
        color: white;
        padding: 10px 20px;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        margin-top: 10px;
        display: block;
        width: 100%;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .btn-pay:hover {
        opacity: 0.85;
        transform: translateY(-2px);
    }

    /* ===== PAYMENT MODAL ===== */
    .coin-selector {
        display: flex;
        gap: 1rem;
        margin: 2rem 0;
    }

    .coin-selector label {
        flex: 1;
        padding: 1rem;
        text-align: center;
        background: var(--split-bg);
        border: 2px solid transparent;
        border-radius: 12px;
        cursor: pointer;
        font-weight: 600;
        transition: all 0.3s ease;
        color: var(--modal-text);
    }

    .coin-selector input[type="radio"] {
        display: none;
    }

    .coin-selector input[type="radio"]:checked + label {
        background: linear-gradient(135deg, var(--accent), var(--info));
        color: white;
        border-color: var(--accent);
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(16, 185, 129, 0.3);
    }

    .crypto-details {
        background: var(--crypto-details-bg);
        padding: 1rem;
        border-radius: 12px;
        margin: 1rem 0;
    }

    .crypto-details p {
        margin: 0.5rem 0;
        font-size: 0.9rem;
        color: var(--modal-text);
    }

    .crypto-details strong {
        color: var(--accent);
    }
    /* ===== RESET BUTTON - EXACTLY MATCHES EXISTING BUTTON STYLES ===== */
    .btn-reset {
        background: linear-gradient(135deg, var(--accent), var(--info)) !important;
        color: white !important;
    }

    .btn-reset:hover {
        transform: translateY(-3px) scale(1.05);
        box-shadow: 0 10px 30px rgba(16, 185, 129, 0.5) !important;
    }
    /* Failed Payment Styles */
    .btn-loyalty-failed {
        background: rgba(231, 76, 60, 0.15);
        color: #e74c3c;
        border: 2px solid #e74c3c;
    }
    .btn-loyalty-failed:hover {
        background: rgba(231, 76, 60, 0.25);
    }
    /* ===== SUCCESS MODAL ===== */
    .success-icon {
        font-size: 4rem;
        text-align: center;
        margin-bottom: 0.5rem;
        animation: bounceIn 0.6s ease;
    }
    /* ===== REVENUE ICON ===== */
    .revenue-icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
        width: 48px;
        height: 48px;
        flex-shrink: 0;
        margin-right: 14px;
        transition: all 0.3s ease;
        /* Remove any background */
        background: transparent !important;
        /* Remove any border */
        border: none !important;
        /* Remove any box shadow */
        box-shadow: none !important;
    }

    /* Remove hover background completely */
    .revenue-item:hover .revenue-icon-wrapper {
        transform: scale(1.1);
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }

    .revenue-icon-wrapper .revenue-icon {
        font-size: 32px;
        line-height: 1;
        display: flex;
        align-items: center;
        /* Remove any background from the icon itself */
        background: transparent !important;
    }

    /* Remove background from active contract icon wrapper */
    .revenue-item.active-contract-simplified .revenue-icon-wrapper {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        animation: pulseIcon 2s infinite;
    }

    @keyframes pulseIcon {
        0%, 100% {
            transform: scale(1);
        }
        50% {
            transform: scale(1.1);
        }
    }

    /* Make sure the revenue header also has no background issues */
    .revenue-header {
        background: transparent !important;
    }

    .revenue-item {
        background: var(--revenue-header-bg);
        /* This is the background you're seeing - change it to match text background */
    }

    /* If you want it to match the text background, use this: */
    .revenue-item {
        background: transparent !important;
        border: 1px solid var(--glass-border);
    }

    /* Dark mode - ensure transparency */
    @media (prefers-color-scheme: dark) {
        .revenue-icon-wrapper {
            background: transparent !important;
        }
        
        .revenue-item:hover .revenue-icon-wrapper {
            background: transparent !important;
        }
    }

    @keyframes pulseIcon {
        0%, 100% {
            transform: scale(1);
        }
        50% {
            transform: scale(1.08);
        }
    }

    /* Dark mode adjustments */
    @media (prefers-color-scheme: dark) {
        .revenue-icon-wrapper {
            background: rgba(255, 255, 255, 0.05);
        }
        
        .revenue-item:hover .revenue-icon-wrapper {
            background: rgba(16, 185, 129, 0.2);
        }
    }

    /* Mobile responsive */
    @media (max-width: 768px) {
        .revenue-icon-wrapper {
            min-width: 40px;
            width: 40px;
            height: 40px;
            margin-right: 10px;
        }
        
        .revenue-icon-wrapper .revenue-icon {
            font-size: 17px;
        }
    }
    @keyframes bounceIn {
        0% { transform: scale(0); opacity: 0; }
        50% { transform: scale(1.3); }
        70% { transform: scale(0.9); }
        100% { transform: scale(1); opacity: 1; }
    }

    #applySuccessModal .modal-content h2 {
        text-align: center;
    }

    #applySuccessModal .modal-content p {
        text-align: center;
    }

    #applySuccessModal .modal-actions button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(16, 185, 129, 0.4);
    }
    .btn-pay-failed {
        background: #e74c3c !important;
        color: white !important;
    }
    .btn-pay-failed:hover {
        background: #c0392b !important;
    }

    .failed-warning {
        border-left: 4px solid #e74c3c;
        padding: 0.8rem 1rem;
        background: rgba(231, 76, 60, 0.1);
        border-radius: 4px;
    }

    /* Status badge for failed */
    .status-failed {
        background: rgba(231, 76, 60, 0.15);
        color: #e74c3c;
        border: 1px solid rgba(231, 76, 60, 0.3);
    }

    .status-badge-modern.status-failed {
        background: rgba(231, 76, 60, 0.15);
        color: #e74c3c;
    }

    /* In the revenue summary cards */
    .summary-card.failed {
        border-left: 4px solid #e74c3c;
    }

    .btc-address {
        display: block;
        padding: 1rem;
        background: var(--address-bg);
        border-radius: 12px;
        font-family: 'Monaco', 'Menlo', monospace;
        font-size: 0.9rem;
        word-break: break-all;
        border: 1px dashed var(--accent);
        cursor: pointer;
        transition: all 0.3s ease;
        color: var(--modal-text);
    }

    .btc-address:hover {
        background: rgba(16, 185, 129, 0.1);
        transform: scale(1.02);
    }

    .btn-full {
        width: 100%;
        padding: 14px;
        border: none;
        border-radius: 12px;
        font-weight: 600;
        font-size: 1rem;
        cursor: pointer;
        transition: all 0.3s ease;
        color: white;
    }

    .btn-paid {
        background: linear-gradient(135deg, var(--accent), var(--info));
        color: white;
        margin-top: 1rem;
    }

    .btn-paid:hover:not(:disabled) {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(16, 185, 129, 0.4);
    }

    .btn-paid:disabled {
        background: linear-gradient(135deg, #6b7280, #4b5563);
        cursor: not-allowed;
        opacity: 0.6;
        transform: none;
    }

    #copyAddressBtn {
        background: var(--split-bg);
        color: var(--modal-text);
        border: 1px solid var(--glass-border);
        margin: 1rem 0;
    }

    #copyAddressBtn:hover {
        background: rgba(16, 185, 129, 0.1);
        border-color: var(--accent);
        transform: translateY(-2px);
    }

    /* ===== CHECKBOX CONTAINER ===== */
    .checkbox-container {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        margin: 1.5rem 0;
        padding: 12px;
        background: var(--checkbox-bg);
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.3s ease;
        color: var(--modal-text);
    }

    .checkbox-container:hover {
        background: rgba(16, 185, 129, 0.1);
    }

    .checkbox-container input[type="checkbox"] {
        width: 20px;
        height: 20px;
        cursor: pointer;
        accent-color: var(--accent);
    }

    .checkbox-container input[type="checkbox"]:checked {
        transform: scale(1.05);
    }

    /* ===== DISCLAIMER TEXT ===== */
    .disclaimer {
        font-size: 0.75rem;
        text-align: center;
        margin-top: 1rem;
        opacity: 0.6;
        padding: 0.5rem;
        color: var(--modal-text);
    }

    /* ===== HIDE SCROLLBAR FOR MODAL CONTENT ===== */
    .modal-content {
        -ms-overflow-style: none;
        scrollbar-width: none;
    }

    .modal-content::-webkit-scrollbar {
        display: none;
    }

    @media (max-width: 768px) {
        .split-container {
            flex-direction: column;
            gap: 1rem;
        }
        .coin-selector {
            flex-direction: column;
        }
    }

    /* ===== HISTORY SECTION ===== */
    .history-section {
        margin-top: 1rem;
        max-height: 300px;
        overflow-y: auto;
        padding: 1rem;
        background: var(--history-bg);
        border-radius: 12px;
    }

    .history-item {
        display: flex;
        justify-content: space-between;
        padding: 0.75rem 1rem;
        border-bottom: 1px solid var(--history-border);
        transition: all 0.3s ease;
        border-radius: 8px;
        color: var(--modal-text);
    }

    .history-item:hover {
        background: rgba(16, 185, 129, 0.1);
        transform: translateX(5px);
    }

    .history-symbol {
        font-weight: 600;
        color: var(--modal-text);
    }

    .history-amount-won {
        color: var(--success);
        font-weight: 700;
    }

    .history-amount-lost {
        color: var(--danger);
        font-weight: 700;
    }

    /* ===== ANIMATIONS ===== */
    @keyframes fadeInDown {
        from {
            opacity: 0;
            transform: translateY(-20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes fadeIn {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }

    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateX(-20px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }

    @keyframes cardAppear {
        from {
            opacity: 0;
            transform: scale(0.9);
        }
        to {
            opacity: 1;
            transform: scale(1);
        }
    }

    @keyframes modalSlideUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes pulse {
        0%, 100% {
            transform: scale(1);
        }
        50% {
            transform: scale(1.02);
        }
    }

    /* ===== CUSTOM SCROLLBAR ===== */
    ::-webkit-scrollbar {
        width: 8px;
    }

    ::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.05);
        border-radius: 10px;
    }

    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, var(--accent), var(--info));
        border-radius: 10px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, var(--accent-hover), #2563eb);
    }

    /* ===== RE-ENROLLMENT MODAL ===== */
    .reenroll-instructions {
        background: var(--reenroll-bg);
        border-left: 4px solid var(--info);
        padding: 1.5rem;
        margin: 1.5rem 0;
        border-radius: 0 8px 8px 0;
        text-align: left;
    }

    .reenroll-instructions h4 {
        color: var(--info);
        margin-bottom: 1rem;
        font-size: 1.1rem;
    }

    .reenroll-instructions ul {
        list-style: none;
        padding-left: 0;
    }

    .reenroll-instructions ul li {
        position: relative;
        padding-left: 28px;
        margin-bottom: 12px;
        color: var(--modal-text);
        font-size: 0.95rem;
    }

    .reenroll-instructions ul li::before {
        content: '⚠';
        position: absolute;
        left: 0;
        top: 0;
        color: var(--warning);
        font-size: 1.1rem;
    }

    .reenroll-instructions .consequence-note {
        margin-top: 1.2rem;
        padding: 0.8rem;
        background: var(--consequence-bg);
        border-radius: 6px;
        font-size: 0.9rem;
        color: var(--danger);
        font-weight: 500;
    }

    .checkbox-container-legal {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        margin: 1.5rem 0;
        padding: 1rem;
        background: var(--checkbox-bg);
        border-radius: 8px;
        cursor: pointer;
        color: var(--modal-text);
    }

    .checkbox-container-legal input[type="checkbox"] {
        margin-top: 3px;
        width: 18px;
        height: 18px;
        accent-color: var(--success);
        flex-shrink: 0;
    }

    .checkbox-container-legal label {
        font-size: 0.9rem;
        color: var(--modal-text);
        line-height: 1.5;
        cursor: pointer;
    }

    .reenroll-confirm-btn {
        width: 100%;
        padding: 14px;
        margin-top: 15px;
        background: var(--success);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 1.1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s;
    }

    .reenroll-confirm-btn:disabled {
        background: #555;
        color: #999;
        cursor: not-allowed;
        opacity: 0.6;
    }

    .reenroll-confirm-btn:not(:disabled):hover {
        background: #27ae60;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(46, 204, 113, 0.3);
    }

    /* ===== PASSKEY VERIFICATION OVERLAY ===== */
    .passkey-verification-overlay {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: var(--modal-overlay);
        z-index: 10001;
        align-items: center;
        justify-content: center;
    }

    .passkey-verification-overlay.active {
        display: flex;
    }

    .passkey-verification-box {
        background: var(--passkey-bg);
        padding: 2.5rem;
        border-radius: 16px;
        width: 90%;
        max-width: 450px;
        text-align: center;
        border: 1px solid var(--glass-border);
    }

    .passkey-verification-box h3 {
        margin-bottom: 1rem;
        color: var(--passkey-text);
        font-size: 1.5rem;
    }

    .passkey-verification-box p {
        color: var(--passkey-text);
        opacity: 0.8;
    }

    .passkey-verification-box input {
        width: 100%;
        padding: 12px;
        margin: 10px 0;
        border: 2px solid var(--input-border);
        border-radius: 8px;
        background: var(--input-bg);
        color: var(--input-text);
        font-size: 1rem;
        transition: border-color 0.3s;
    }

    .passkey-verification-box input::placeholder {
        color: var(--input-placeholder);
    }

    .passkey-verification-box input:focus {
        outline: none;
        border-color: var(--accent);
    }

    .passkey-verification-box .error-message {
        color: var(--error-color);
        margin-top: 10px;
        display: none;
    }

    .passkey-verification-box .btn-verify-passkey {
        width: 100%;
        padding: 12px;
        margin-top: 15px;
        background: var(--info);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
        transition: background 0.3s;
    }

    .passkey-verification-box .btn-verify-passkey:hover {
        background: #2563eb;
    }

    .passkey-verification-box .btn-verify-passkey:disabled {
        background: #555;
        cursor: not-allowed;
    }

    .passkey-verification-box .btn-cancel {
        width: 100%;
        padding: 12px;
        margin-top: 10px;
        background: #6b7280;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
    }

    .passkey-verification-box .btn-cancel:hover {
        background: #7b8290;
    }

    /* ===== NOTIFICATION SYSTEM ===== */
    .notification-container {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
    }

    .notification-bell {
        position: relative;
        cursor: pointer;
        background: var(--card-light);
        backdrop-filter: blur(10px);
        padding: 12px;
        border-radius: 50%;
        width: 45px;
        height: 45px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--glass-border);
        transition: all 0.3s ease;
        box-shadow: var(--shadow-sm);
    }

    .notification-bell:hover {
        transform: scale(1.05);
        border-color: var(--accent);
        box-shadow: var(--shadow-hover);
    }

    .notification-bell i {
        font-size: 20px;
        color: var(--text);
    }

    .notification-badge {
        position: absolute;
        top: -5px;
        right: -5px;
        background: var(--danger);
        color: white;
        border-radius: 50%;
        width: 20px;
        height: 20px;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        animation: pulse 2s infinite;
    }

    .notification-panel {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100%;
        height: 100%;
        background: var(--modal-bg);
        backdrop-filter: blur(20px);
        z-index: 10000;
        display: none;
        flex-direction: column;
        overflow: hidden;
        animation: slideDown 0.4s ease forwards;
    }

    .notification-panel.active {
        display: flex;
    }

    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-100%);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    /* PASSKEY OVERLAY - Higher z-index */
    .passkey-overlay {
        z-index: 20000 !important;
    }

    .passkey-overlay.active {
        z-index: 20000 !important;
    }

    body:has(.passkey-overlay) .notification-container {
        z-index: 10001 !important;
    }

    .passkey-overlay .passkey-screen {
        position: relative;
        z-index: 20001;
    }

    .passkey-overlay ~ .notification-panel,
    body:has(.passkey-overlay) .notification-panel {
        z-index: 9999 !important;
    }

    .notification-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.5rem 2rem;
        border-bottom: 1px solid var(--glass-border);
        background: var(--bg-secondary);
        position: sticky;
        top: 0;
        z-index: 1;
    }

    .notification-header h3 {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0;
        color: var(--text);
        background: none;
        -webkit-text-fill-color: var(--text);
    }

    .close-notifications {
        background: var(--split-bg);
        border: 1px solid var(--glass-border);
        font-size: 24px;
        cursor: pointer;
        color: var(--text);
        opacity: 0.7;
        transition: all 0.3s ease;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .close-notifications:hover {
        opacity: 1;
        transform: rotate(90deg);
        background: rgba(239, 68, 68, 0.2);
        border-color: var(--danger);
        color: var(--danger);
    }

    .notification-list {
        flex: 1;
        overflow-y: auto;
        padding: 1rem;
        max-height: calc(100vh - 80px);
    }

    .notification-item {
        padding: 1.25rem 1.5rem;
        margin-bottom: 0.75rem;
        border-radius: 16px;
        background: var(--notification-item-bg);
        border: 1px solid var(--glass-border);
        transition: all 0.3s ease;
        cursor: pointer;
        color: var(--text);
    }

    .notification-item:hover {
        background: rgba(16, 185, 129, 0.1);
        transform: translateX(5px);
        border-color: var(--accent);
    }

    .notification-item.unread {
        background: var(--notification-unread-bg);
        border-left: 4px solid var(--info);
    }

    .notification-item.success {
        border-left: 4px solid var(--success);
    }

    .notification-item.error {
        border-left: 4px solid var(--danger);
    }

    .notification-item.warning {
        border-left: 4px solid var(--warning);
    }

    .notification-section {
        font-size: 0.75rem;
        opacity: 0.6;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: var(--text-secondary);
    }

    .notification-message {
        font-size: 1rem;
        line-height: 1.5;
        margin-bottom: 0.75rem;
        color: var(--text);
    }

    .notification-time {
        font-size: 0.75rem;
        opacity: 0.5;
        display: flex;
        align-items: center;
        gap: 5px;
        color: var(--text-secondary);
    }

    .empty-notifications {
        text-align: center;
        padding: 4rem 2rem;
        opacity: 0.6;
        font-size: 1rem;
        color: var(--text);
    }

    /* ===== REVENUE HISTORY MODAL ===== */
    #revenueHistoryModal.modal {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100%;
        height: 100%;
        background: var(--modal-overlay);
        backdrop-filter: blur(20px);
        z-index: 10000;
        padding: 0;
    }

    #revenueHistoryModal .modal-content {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100%;
        height: 100%;
        max-width: none;
        max-height: none;
        border-radius: 0;
        padding: 2rem;
        display: flex;
        flex-direction: column;
        background: var(--modal-bg);
        color: var(--modal-text);
        margin: 0;
        overflow: hidden;
        border: none;
    }

    #revenueHistoryModal h2 {
        margin-bottom: 1rem;
        flex-shrink: 0;
        color: var(--modal-text);
        background: none;
        -webkit-text-fill-color: var(--modal-text);
    }

    .revenue-history-container {
        flex: 1;
        overflow-y: auto;
        overflow-x: hidden;
        padding: 0;
        margin: 1rem 0;
        width: 100%;
        -ms-overflow-style: none;
        scrollbar-width: thin;
    }

    .revenue-history-container::-webkit-scrollbar {
        width: 8px;
    }

    .revenue-history-container::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.1);
        border-radius: 10px;
    }

    .revenue-history-container::-webkit-scrollbar-thumb {
        background: var(--accent);
        border-radius: 10px;
    }

    .revenue-item {
        background: var(--revenue-header-bg);
        border-radius: 5px;
        margin-bottom: 12px;
        overflow: hidden;
        transition: all 0.3s ease;
        border: 1px solid var(--revenue-border);
        width: 100%;
        box-sizing: border-box;
        display: block;
        color: var(--modal-text);
    }

    .revenue-item:hover {
        border-color: var(--accent);
    }

    .revenue-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        cursor: pointer;
        background: var(--revenue-header-bg);
        transition: all 0.3s ease;
        width: 100%;
        box-sizing: border-box;
        gap: 15px;
        color: var(--modal-text);
    }

    .revenue-header:hover {
        background: rgba(16, 185, 129, 0.1);
    }

    .revenue-header-left {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1;
    }

    .revenue-date-range {
        font-weight: 600;
        font-size: 0.75rem;
        color: var(--text-muted);
        opacity: 0.9;
        word-break: break-word;
    }

    .revenue-user-share {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--success);
    }

    .revenue-status {
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 600;
        white-space: nowrap;
        flex-shrink: 0;
    }

    .revenue-status.completed {
        color: var(--success);
    }

    .revenue-status.pending {
        color: var(--warning);
    }

    .revenue-status.loss {
        color: var(--danger);
    }

    .revenue-status.active {
        color: var(--info);
    }

    .revenue-details {
        display: none;
        padding: 16px 20px;
        background: var(--revenue-details-bg);
        border-top: 1px solid var(--glass-border);
        width: 100%;
        box-sizing: border-box;
        overflow-x: hidden;
        color: var(--modal-text);
    }

    .revenue-details.active {
        display: block;
        animation: slideDown 0.3s ease;
    }

    .revenue-detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
        padding: 8px 0;
        border-bottom: 1px solid var(--revenue-border);
        width: 100%;
        box-sizing: border-box;
    }

    .revenue-detail-row:last-child {
        border-bottom: none;
    }

    .revenue-detail-label {
        font-weight: 500;
        opacity: 0.7;
        font-size: 0.85rem;
        flex-shrink: 0;
        color: var(--text-secondary);
    }

    .revenue-detail-value {
        font-weight: 600;
        font-size: 0.9rem;
        text-align: right;
        word-break: break-word;
        flex-shrink: 0;
        color: var(--modal-text);
    }

    .revenue-detail-value.profit-positive {
        color: var(--success);
    }

    .revenue-detail-value.profit-negative {
        color: var(--danger);
    }

    .empty-revenue {
        text-align: center;
        padding: 60px 20px;
        opacity: 0.7;
        font-size: 1rem;
        color: var(--modal-text);
    }

    #revenueHistoryModal .modal-actions {
        margin-top: 1rem;
        padding-top: 1rem;
        border-top: 1px solid var(--glass-border);
        justify-content: flex-end;
        flex-shrink: 0;
    }

    #revenueHistoryModal .modal-actions button {
        padding: 10px 24px;
        font-size: 0.9rem;
        background: #6b7280;
        color: white;
        border: none;
        border-radius: 8px;
        cursor: pointer;
    }

    #revenueHistoryModal .modal-actions button:hover {
        background: #7b8290;
    }

    .revenue-item.active-contract-simplified .revenue-user-share {
        color: var(--success);
        font-weight: bold;
        font-size: 0.9rem;
    }

    .revenue-item.active-contract-simplified .revenue-date-range {
        color: var(--text-muted);
        font-weight: 600;
    }

    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-5px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    /* ===== RESPONSIVE ===== */
    @media (max-width: 768px) {
        .stat-card h2 {
            font-size: 2rem;
        }
        
        .trades-count {
            font-size: 3rem;
        }
        
        .loyalty-status-msg {
            font-size: 1.2rem;
        }
        
        .modal-content {
            padding: 1.5rem;
        }
        
        .coin-selector {
            flex-direction: column;
        }

        .notification-header {
            padding: 1rem 1.25rem;
        }
        
        .notification-header h3 {
            font-size: 1.25rem;
        }
        
        .notification-item {
            padding: 1rem;
        }
        
        .notification-message {
            font-size: 0.9rem;
        }

        #revenueHistoryModal .modal-content {
            padding: 1rem;
        }
        
        .revenue-header {
            padding: 12px 16px;
            flex-direction: column;
            align-items: flex-start;
            gap: 8px;
        }
        
        .revenue-status {
            align-self: flex-start;
        }
        
        .revenue-details {
            padding: 12px 16px;
        }
        
        .revenue-detail-row {
            flex-direction: column;
            align-items: flex-start;
            gap: 4px;
        }
        
        .revenue-detail-value {
            text-align: left;
        }
    }

    /* ===== PREVENT PULL-TO-REFRESH ===== */
    html {
        overscroll-behavior: none;
    }

    body {
        overscroll-behavior: none;
        position: relative;
    }

    .scrollable-container {
        overscroll-behavior: contain;
    }

    /* ===== BACKGROUND EFFECT ===== */
    body::before {
        content: ""; 
        position: absolute; 
        inset: 0;
        background: var(--bg-secondary);
        background-size: cover, cover, 120px 120px; 
        opacity: 0.5; 
        pointer-events: none; 
        z-index: -1;
    }

    @media (prefers-color-scheme: light) {
        body::before { 
            opacity: 0.1; 
            background-blend-mode: multiply; 
        }
    }

    /* ===== APPLY MODAL ===== */
    .apply-instructions {
        background: var(--checkbox-bg);
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }

    .apply-instructions ul {
        list-style: none;
        padding-left: 0;
    }

    .apply-instructions ul li {
        margin-bottom: 10px;
        color: var(--modal-text);
    }

    .apply-warning {
        background: rgba(255, 193, 7, 0.1);
        border-left: 4px solid var(--warning);
        padding: 1rem;
        margin: 1rem 0;
    }

    .apply-warning strong {
        color: var(--warning);
    }

    .apply-warning p {
        margin-top: 0.5rem;
        color: var(--modal-text);
    }

    /* ===== ADDITIONAL FIXES FOR LIGHT MODE ===== */
    /* Ensure all text in modals is visible in light mode */
    .modal-content h2,
    .modal-content h3,
    .modal-content h4,
    .modal-content p,
    .modal-content label,
    .modal-content span,
    .modal-content div {
        color: var(--modal-text);
    }

    /* Fix for split items in light mode */
    .split-item h4 {
        color: var(--split-text);
    }

    .split-item p {
        color: var(--split-text);
    }

    /* Fix for coin selector labels in light mode */
    .coin-selector label {
        color: var(--modal-text);
    }

    /* Fix for checkbox labels */
    .checkbox-container label {
        color: var(--modal-text);
    }

    /* Fix for crypto details in light mode */
    .crypto-details p {
        color: var(--modal-text);
    }

    /* Fix for disconnect section labels */
    .disconnect-verify-section label {
        color: var(--modal-text);
    }

    /* Fix for re-enrollment instructions */
    .reenroll-instructions ul li {
        color: var(--modal-text);
    }

    .reenroll-instructions .consequence-note {
        color: var(--danger);
    }

    /* Fix for notification items */
    .notification-item .notification-message {
        color: var(--text);
    }

    .notification-item .notification-section {
        color: var(--text-secondary);
    }

    .notification-item .notification-time {
        color: var(--text-secondary);
    }

    /* Fix for revenue history */
    .revenue-item .revenue-detail-label {
        color: var(--text-secondary);
    }

    .revenue-item .revenue-detail-value {
        color: var(--modal-text);
    }

    .revenue-item .revenue-date-range {
        color: var(--text-muted);
    }
</style>
