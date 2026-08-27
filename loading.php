<?php
// loading.php - Custom Loading Overlay Script
// This should be included at the VERY TOP of your HTML, right after <body> tag
?>
<style>
    /* Loading Overlay Styles */
    #customLoadingOverlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.3); /* Semi-transparent background */
        backdrop-filter: blur(1px); /* Reduced blur effect */
        -webkit-backdrop-filter: blur(1px); /* For Safari */
        display: flex !important;
        justify-content: center;
        align-items: center;
        flex-direction: column;
        z-index: 99999;
        transition: opacity 0.5s ease;
        pointer-events: none;
    }
    
    #customLoadingOverlay.fade-out {
        opacity: 0;
        pointer-events: none;
    }
    
    /* Hidden state - but keep it rendered */
    #customLoadingOverlay.hidden {
        display: none !important;
    }
    
    .loading-container {
        text-align: center;
    }
    
    /* Individual letter styling with green-black-white gradient */
    .letter-wave {
        display: inline-block;
        font-size: 2.5rem;
        font-weight: 900;
        font-family: 'Arial', 'Helvetica', sans-serif;
        letter-spacing: 2px;
        background-size: 300% 100%;
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: colorWaveGradientDark 3s ease-in-out infinite;
        text-shadow: none;
        opacity: 1;
        transition: opacity 0.5s ease;
    }
    
    .letter-wave:nth-child(1) { animation-delay: 0s; }
    .letter-wave:nth-child(2) { animation-delay: 0.2s; }
    .letter-wave:nth-child(3) { animation-delay: 0.3s; }
    .letter-wave:nth-child(4) { animation-delay: 0.4s; }
    .letter-wave:nth-child(5) { animation-delay: 0.5s; }
    .letter-wave:nth-child(6) { animation-delay: 0.6s; }
    .letter-wave:nth-child(7) { animation-delay: 0.7s; }
    
    /* Fade out the text with the overlay */
    #customLoadingOverlay.fade-out .letter-wave {
        opacity: 0;
    }
    
    /* DARK MODE: White + Green gradient */
    @keyframes colorWaveGradientDark {
        0% {
            background: linear-gradient(90deg, #00ff41, #ffffff, #00cc33, #66ff88, #ffffff);
            background-size: 300% 100%;
            background-position: 0% 50%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        25% {
            background: linear-gradient(90deg, #ffffff, #00ff41, #66ff88, #ffffff, #00cc33);
            background-size: 300% 100%;
            background-position: 100% 50%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        50% {
            background: linear-gradient(90deg, #00cc33, #66ff88, #ffffff, #00ff41, #ffffff);
            background-size: 300% 100%;
            background-position: 0% 50%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        75% {
            background: linear-gradient(90deg, #66ff88, #ffffff, #00ff41, #ffffff, #00cc33);
            background-size: 300% 100%;
            background-position: 100% 50%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        100% {
            background: linear-gradient(90deg, #00ff41, #ffffff, #00cc33, #66ff88, #ffffff);
            background-size: 300% 100%;
            background-position: 0% 50%;
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }
    }
    
    /* LIGHT MODE: Black + Green gradient */
    @media (prefers-color-scheme: light) {
        #customLoadingOverlay {
            background: rgba(255, 255, 255, 0.4);
        }
        
        .letter-wave {
            animation: colorWaveGradientLight 3s ease-in-out infinite;
        }
        
        @keyframes colorWaveGradientLight {
            0% {
                background: linear-gradient(90deg, #00cc33, #1a1a1a, #00ff41, #008c22, #000000);
                background-size: 300% 100%;
                background-position: 0% 50%;
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            25% {
                background: linear-gradient(90deg, #1a1a1a, #00ff41, #008c22, #000000, #00cc33);
                background-size: 300% 100%;
                background-position: 100% 50%;
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            50% {
                background: linear-gradient(90deg, #008c22, #000000, #00cc33, #1a1a1a, #00ff41);
                background-size: 300% 100%;
                background-position: 0% 50%;
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            75% {
                background: linear-gradient(90deg, #000000, #00cc33, #1a1a1a, #00ff41, #008c22);
                background-size: 300% 100%;
                background-position: 100% 50%;
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            100% {
                background: linear-gradient(90deg, #00cc33, #1a1a1a, #00ff41, #008c22, #000000);
                background-size: 300% 100%;
                background-position: 0% 50%;
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
        }
    }

    /* Small screen adjustments */
    @media (max-width: 600px) {
        .letter-wave {
            font-size: 1.8rem !important;
        }
    }
</style>

<div id="customLoadingOverlay">
    <div class="loading-container">
        <div>
            <span class="letter-wave">H</span>
            <span class="letter-wave">a</span>
            <span class="letter-wave">r</span>
            <span class="letter-wave">v</span>
            <span class="letter-wave">H</span>
            <span class="letter-wave">u</span>
            <span class="letter-wave">b</span>
        </div>
    </div>
</div>

<script>
// loading.js - Custom Loading Manager
(function() {
    'use strict';
    
    // Configuration
    const CONFIG = {
        minDisplayTime: 500,        // Minimum time to show loading (ms) - reduced for faster response
        maxDisplayTime: 10000,      // Maximum time before forcing hide (ms)
        debug: false               // Enable console logs for debugging
    };
    
    class CustomLoadingManager {
        constructor() {
            this.overlay = document.getElementById('customLoadingOverlay');
            this.startTime = Date.now();
            this.isComplete = false;
            this.isForced = false;
            this.timeoutId = null;
            this.isVisible = true;
            
            if (CONFIG.debug) {
                console.log('Loading overlay initialized at', new Date().toISOString());
            }
            
            this.init();
        }
        
        init() {
            // Ensure overlay is visible immediately
            this.show();
            
            // Set maximum timeout (safety net)
            this.timeoutId = setTimeout(() => {
                if (!this.isComplete) {
                    if (CONFIG.debug) {
                        console.warn('Loading timeout - forcing complete');
                    }
                    this.forceComplete();
                }
            }, CONFIG.maxDisplayTime);
            
            // Listen for page load events
            if (document.readyState === 'complete') {
                this.handleLoadComplete();
            } else {
                window.addEventListener('load', () => this.handleLoadComplete());
            }
            
            // Also handle DOMContentLoaded as fallback
            if (document.readyState !== 'loading') {
                // Already loaded or interactive
                this.handleLoadComplete();
            } else {
                document.addEventListener('DOMContentLoaded', () => {
                    if (CONFIG.debug) {
                        console.log('DOMContentLoaded fired');
                    }
                    // Don't hide immediately - wait for full load
                });
            }
            
            // Handle navigation events (for SPA or AJAX)
            this.interceptNavigation();
        }
        
        show() {
            if (this.overlay) {
                this.overlay.classList.remove('fade-out', 'hidden');
                this.overlay.style.display = 'flex';
                this.overlay.style.opacity = '1';
                this.overlay.style.pointerEvents = 'none';
                this.isVisible = true;
                
                if (CONFIG.debug) {
                    console.log('Loading overlay shown');
                }
            }
        }
        
        handleLoadComplete() {
            if (this.isComplete) return;
            
            if (CONFIG.debug) {
                console.log('Page load complete at', new Date().toISOString());
            }
            
            // Ensure minimum display time
            const elapsed = Date.now() - this.startTime;
            const remaining = Math.max(0, CONFIG.minDisplayTime - elapsed);
            
            if (CONFIG.debug) {
                console.log(`Elapsed: ${elapsed}ms, Remaining: ${remaining}ms`);
            }
            
            // Small delay to ensure everything is rendered
            setTimeout(() => {
                this.completeLoading();
            }, remaining + 100);
        }
        
        completeLoading() {
            if (this.isComplete) return;
            this.isComplete = true;
            
            if (CONFIG.debug) {
                console.log('Loading completed at', new Date().toISOString());
            }
            
            // Fade out and hide
            if (this.overlay) {
                this.overlay.classList.add('fade-out');
                setTimeout(() => {
                    this.hide();
                }, 500);
            }
        }
        
        forceComplete() {
            if (this.isComplete) return;
            this.isForced = true;
            
            if (CONFIG.debug) {
                console.log('Loading force completed');
            }
            
            this.completeLoading();
        }
        
        hide() {
            if (this.overlay) {
                this.overlay.classList.add('hidden');
                this.isVisible = false;
                
                if (CONFIG.debug) {
                    console.log('Loading overlay hidden');
                }
            }
            
            // Clean up timeout
            if (this.timeoutId) {
                clearTimeout(this.timeoutId);
                this.timeoutId = null;
            }
            
            // Dispatch event for other scripts
            document.dispatchEvent(new CustomEvent('loadingComplete'));
        }
        
        interceptNavigation() {
            // Intercept link clicks to show loading for navigation
            document.addEventListener('click', (e) => {
                const link = e.target.closest('a');
                if (link && link.href && 
                    link.target !== '_blank' && 
                    !link.href.startsWith('javascript:') &&
                    !link.href.startsWith('#') &&
                    link.hostname === window.location.hostname) {
                    
                    // Don't intercept if it's a download or email link
                    if (link.download || link.href.startsWith('mailto:')) return;
                    
                    // Check if it's a hash link (same page anchor)
                    if (link.getAttribute('href')?.startsWith('#')) return;
                    
                    if (CONFIG.debug) {
                        console.log('Navigation intercepted:', link.href);
                    }
                    
                    // Show loading for navigation
                    this.show();
                    this.isComplete = false;
                    
                    // Reset start time for minimum display
                    this.startTime = Date.now();
                    
                    // Safety timeout
                    setTimeout(() => {
                        if (!this.isComplete) {
                            if (CONFIG.debug) {
                                console.warn('Navigation timeout - forcing complete');
                            }
                            this.forceComplete();
                        }
                    }, CONFIG.maxDisplayTime);
                }
            });
            
            // Intercept form submissions
            document.addEventListener('submit', (e) => {
                const form = e.target;
                if (form && form.action && 
                    !form.target === '_blank') {
                    
                    if (CONFIG.debug) {
                        console.log('Form submission intercepted:', form.action);
                    }
                    
                    this.show();
                    this.isComplete = false;
                    this.startTime = Date.now();
                    
                    setTimeout(() => {
                        if (!this.isComplete) {
                            if (CONFIG.debug) {
                                console.warn('Form submission timeout - forcing complete');
                            }
                            this.forceComplete();
                        }
                    }, CONFIG.maxDisplayTime);
                }
            });
        }
    }
    
    // Initialize IMMEDIATELY - even before DOMContentLoaded
    let loadingManager;
    
    // Create the overlay element if it doesn't exist (safety)
    if (!document.getElementById('customLoadingOverlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'customLoadingOverlay';
        overlay.innerHTML = `
            <div class="loading-container">
                <div>
                    <span class="letter-wave">H</span>
                    <span class="letter-wave">a</span>
                    <span class="letter-wave">r</span>
                    <span class="letter-wave">v</span>
                    <span class="letter-wave">H</span>
                    <span class="letter-wave">u</span>
                    <span class="letter-wave">b</span>
                </div>
            </div>
        `;
        document.body.prepend(overlay);
    }
    
    // Initialize immediately
    loadingManager = new CustomLoadingManager();
    
    // Expose for debugging or manual control
    window.loadingManager = loadingManager;
    
})();
</script>