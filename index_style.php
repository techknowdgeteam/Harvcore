
<style>
        /* index_style.php MODIFIED STYLES for Light Mode (default) and Dark Mode */
    :root { 
        --bg: #fff; 
        --text: #000000; 
        --accent: #2e8b57;
        --input-bg: #f0f2f5; 
        --section-bg: #fff;
        --section-shadow: 0 4px 12px rgba(0,0,0,0.08); 
        --header-bg: #f5f5f5; 
        --profile-bg: #e9ebee; 
        --profile-icon-bg: #ccc;
        --profile-details-bg: #f9f9f9;
        --profile-details-border: #ddd;
    }
    @media (prefers-color-scheme: dark) {
        :root { 
            --bg: #000; 
            --text: #e4e6eb; 
            --accent: #2e8b57;
            --input-bg: #1a1a1a; 
            --section-bg: rgba(255,255,255,0.05); 
            --section-shadow: none; 
            --header-bg: rgba(0,0,0,0.3);
            --profile-bg: #1a1a1a; 
            --profile-icon-bg: #444;
            --profile-details-bg: #0d0d0d;
            --profile-details-border: #333;
        }
    }
    /* Force true black text in light mode */
    @media (prefers-color-scheme: light) {
        body, 
        .container, 
        .section, 
        .info-card,
        .info-card p,
        .info-card li,
        .welcome-message,
        .profile-details p,
        .modal-content p,
        p, span, li, div, h1, h2, h3, h4 {
            color: #000000 !important;
            opacity: 1 !important;
        }
        
        .info-card {
            background: rgba(0,0,0,0.03);
        }
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
        font-family: 'Segoe UI', sans-serif;
        background: var(--bg);
        color: var(--text);
        height: 100vh;
        overflow: hidden; /* Added: prevents vertical scroll on body */
        position: relative;
    }
    html, body { 
        -ms-overflow-style: none; 
        scrollbar-width: none; 
    }
    html::-webkit-scrollbar, body::-webkit-scrollbar { 
        display: none; 
    }
    .container, .modal-content { 
        overflow-y: auto; 
        -ms-overflow-style: none; 
        scrollbar-width: none; 
    }
    .container::-webkit-scrollbar, .modal-content::-webkit-scrollbar { 
        display: none; 
    }
    /* Background effects */
    body::before {
        content: ""; 
        position: absolute; 
        inset: 0;
        background: radial-gradient(circle at 20% 80%, #1a0033 0%, transparent 50%),
                    radial-gradient(circle at 80% 20%, #000033 0%, transparent 50%),
                    url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><circle cx="10" cy="10" r="1" fill="white"/><circle cx="30" cy="70" r="1.5" fill="white"/><circle cx="70" cy="30" r="1" fill="white"/><circle cx="90" cy="80" r="1.2" fill="white"/><circle cx="50" cy="50" r="1.8" fill="white"/></svg>') repeat;
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
        body, html {
            color: black;
        }
    }
    .custom-body {
        width: 100%;
        height: 100%;
        background: none;
        overflow-y: auto; /* Allows vertical scroll only in custom-body */
        -ms-overflow-style: none; /* Hides scrollbar in IE/Edge */
        scrollbar-width: none; /* Hides scrollbar in Firefox */
    }
    .custom-body::-webkit-scrollbar {
        display: none; /* Hides scrollbar in Chrome/Safari/Opera for custom scroller */
    }
    .container { height: 100vh; padding: 2rem; }
</style>
<style>

    header { 
        position: relative; text-align: center; padding: 1rem 2rem 2rem; 
        background: var(--header-bg); 
        border-radius: 15px; margin-bottom: 2rem; 
        min-height: 120px; 
    }
    h1 { font-size: 4rem; color: var(--accent); margin-bottom: 0.5rem; }
    
    /* Welcome message styling */
    .welcome-message {
        font-size: 1.2rem;
        margin: 0.5rem 0 0;
        color: var(--text);
        opacity: 0.9;
        font-weight: 400;
    }
    .welcome-message strong {
        color: var(--accent);
        font-weight: 600;
    }
    
    h2 { margin: 2rem 0 1rem; color: var(--accent); }
    .section { 
        background: var(--section-bg); 
        padding: 2rem; 
        border-radius: 12px; 
        margin-bottom: 2rem; 
        box-shadow: var(--section-shadow);
    }
    
    /* Hide sections when logged in */
    .logged-in .section:not(.always-show) {
        display: none;
    }
    
    .btn { padding: 1rem 2.5rem; background: var(--accent); color: #000; font-weight: bold; border: none; border-radius: 50px; cursor: pointer; display: inline-block; transition: all 0.3s; }
    .btn:hover { opacity: 0.9; transform: scale(1.05); }
    .btn.blacklisted {
        background: #9e9e9e; color: #555; cursor: default;
        opacity: 0.6; pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .btn.blacklisted:hover { opacity: 0.6; transform: none; }

    /* --- DESKTOP PROFILE STYLES (Minimal Icon & Expandable Card) --- */
    .user-profile-status {
        position: absolute;
        top: 30px; 
        left: 30px; 
        z-index: 20; 
    }
    #profileIcon {
        width: 45px;
        height: 45px;
        border-radius: 50%;
        background: var(--profile-icon-bg);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.8rem; 
        color: var(--text);
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        transition: transform 0.2s, background 0.3s;
        font-weight: bold;
    }
    #profileIcon:hover { transform: scale(1.05); }
    #profileIcon.active { background: var(--accent); color: #000; }

    #profileCard {
        position: absolute;
        top: 0;
        left: 60px; 
        width: 250px;
        background: var(--profile-details-bg);
        border: 1px solid var(--profile-details-border);
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 8px 16px rgba(0,0,0,0.4);
        opacity: 0;
        visibility: hidden;
        transform: translateX(-10px); 
        transition: opacity 0.3s, transform 0.3s, visibility 0.3s;
    }
    #profileCard.active {
        opacity: 1;
        visibility: visible;
        transform: translateX(0);
    }
    .profile-details p {
        margin: 5px 0;
        font-size: 0.95rem;
        word-break: break-all;
    }
    .profile-details strong {
        color: var(--accent);
        margin-right: 5px;
    }

    /* --- MOBILE PROFILE STYLES (Always visible below header) --- */
    #mobileProfileStatus {
        display: none; /* Default to hidden on desktop */
        text-align: left;
        padding: 15px 20px;
        margin: 15px 0 0;
        border-top: 1px solid var(--profile-details-border);
        background: var(--profile-details-bg);
        border-radius: 10px;
    }
    #mobileProfileStatus p {
        margin: 5px 0;
        font-size: 1rem;
    }
    
    /* --- NEW CENTRAL LOGOUT STYLES --- */
    .central-logout {
        text-align: center;
        margin-top: 15px; /* Spacing below the main button */
    }
    .central-logout a {
        font-size: 1rem;
        color: #ff6b6b;
        text-decoration: none;
        padding: 8px 15px;
        border-radius: 5px;
        transition: color 0.2s, background-color 0.2s;
    }
    .central-logout a:hover {
        color: #d63031;
        background-color: rgba(255, 107, 107, 0.1);
    }

    /* --- RESPONSIVE MEDIA QUERIES --- */
    @media (min-width: 768px) {
        /* Desktop: Show icon/card, Hide mobile block */
        #mobileProfileStatus {
            display: none !important;
        }
        .user-profile-status {
            display: block !important;
        }
    }
    @media (max-width: 767px) {
        /* Mobile: Hide icon/card, Show mobile block */
        header {
            min-height: auto; 
            padding-bottom: 1rem; 
        }
        .user-profile-status {
            display: none !important;
        }
        #mobileProfileStatus {
            display: block !important;
        }
    }
    /* --- END RESPONSIVE STYLES --- */

    /* MODAL STYLES */
    .modal { 
        display: none; position: fixed; inset: 0; 
        background: rgba(0,0,0,0.01); 
        backdrop-filter: blur(12px); 
        align-items: center; justify-content: center; z-index: 999; padding: 1rem; 
    }
    .modal.active { display: flex; }
    .modal-content { background: var(--bg); color: var(--text); padding: 2.5rem; border-radius: 20px; width: 90%; max-width: 520px; max-height: 95vh; position: relative; box-shadow: 0 15px 50px rgba(0,0,0,0.6); overflow-y: auto; }
    .close { position: absolute; top: 15px; right: 20px; font-size: 2.5rem; cursor: pointer; opacity: 0.7; }
    .close:hover { opacity: 1; }
    input, select { width: 100%; padding: 14px; margin: 10px 0 16px; border: 1px solid #555; border-radius: 10px; background: var(--input-bg); color: var(--text); font-size: 1rem; }
    select { appearance: none; background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ccc'%3e%3cpath d='M7 10l5 5 5-5z'/%3e%3c/path%3e%3c/svg%3e"); background-repeat: no-repeat; background-position: right 12px center; background-size: 16px; }
    .password-wrapper { position: relative; }
    .password-toggle { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); cursor: pointer; color: var(--text); font-size: 0.9rem; user-select: none; }
    .error-text { color: #ff6b6b; margin-top: 8px; text-align: center; }
    .checkbox-container { display: flex; align-items: center; gap: 12px; margin: 28px 0; font-size: 1rem; cursor: pointer; }
    .checkbox-container input[type="checkbox"] { width: 22px; height: 22px; margin: 0; }
    
    /* Terms box styling */
    .terms-box {
        background: var(--input-bg);
        padding: 1.5rem;
        border-radius: 10px;
        margin: 20px 0;
        border: 1px solid var(--profile-details-border);
    }
    .terms-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--profile-details-border);
    }
    .terms-item:last-child {
        border-bottom: none;
    }
    .terms-label {
        font-weight: bold;
        color: var(--accent);
    }
    .terms-value {
        font-size: 1.2rem;
        font-weight: 600;
    }
    .info-message {
        background: rgba(46, 139, 87, 0.1);
        padding: 1rem;
        border-radius: 8px;
        margin: 20px 0;
        text-align: center;
        border-left: 4px solid var(--accent);
    }
</style>
<style>
    .info-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 20px;
        margin: 30px 0;
    }
    .info-card {
        background: rgba(255,255,255,0.05);
        border-radius: 16px;
        padding: 24px;
        border: 1px solid rgba(255,255,255,0.1);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .info-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        border-color: var(--accent);
    }
    .info-card h3 {
        color: var(--accent);
        margin-bottom: 16px;
        font-size: 1.4rem;
    }
    .info-card p {
        color: #ccc;
        line-height: 1.6;
        margin-bottom: 12px;
    }
    .info-card ul {
        margin: 12px 0 0 20px;
        color: #ccc;
    }
    .info-card li {
        margin: 8px 0;
        line-height: 1.5;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-left: 8px;
    }
    .badge-pending {
        background: #ffa500;
        color: #1a1a2e;
    }
    .edit-btn {
        background: rgba(100, 108, 255, 0.2);
        border: 1px solid var(--accent);
        color: var(--accent);
        padding: 4px 12px;
        border-radius: 20px;
        cursor: pointer;
        font-size: 0.75rem;
        margin-left: 8px;
        transition: all 0.2s;
    }
    .edit-btn:hover {
        background: var(--accent);
        color: #1a1a2e;
    }
    .profile-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
    }
    .modal-small .modal-content {
        max-width: 500px;
        width: 90%;
    }
    .form-group {
        margin-bottom: 18px;
    }
    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-weight: 600;
        color: var(--accent);
    }
    .form-group input, .form-group select {
        width: 100%;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid rgba(255,255,255,0.2);
        background: rgba(0,0,0,0.3);
        color: white;
        font-size: 0.95rem;
    }
    .form-group input:focus, .form-group select:focus {
        outline: none;
        border-color: var(--accent);
    }
    .password-wrapper-edit {
        position: relative;
    }
    .password-wrapper-edit input {
        padding-right: 60px;
    }
    .password-toggle-edit {
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        cursor: pointer;
        color: var(--accent);
        font-size: 0.8rem;
    }
</style>