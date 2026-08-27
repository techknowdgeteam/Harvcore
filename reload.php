<?php
//reload.php - Standalone Pull-to-Reload Script
// Include this file in your index.php after the loading.php
?>
<style>
    /* Pull to Reload Styles */
    #pullToReloadContainer {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        z-index: 99998;
        pointer-events: none;
        height: 0;
        overflow: visible;
    }
    
    #pullToReloadIndicator {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 15px 0;
        background: linear-gradient(180deg, rgba(10, 10, 26, 0.95) 0%, rgba(10, 10, 26, 0) 100%);
        color: var(--accent, #00ff41);
        font-family: 'Arial', 'Helvetica', sans-serif;
        font-size: 0.9rem;
        transform: translateY(-100%);
        transition: none;
        opacity: 0;
        pointer-events: none;
        gap: 12px;
        padding-bottom: 30px;
        min-height: 60px;
        will-change: transform;
    }
    
    #pullToReloadIndicator.visible {
        opacity: 1;
        pointer-events: auto;
    }
    
    #pullToReloadIndicator.release-ready {
        color: #ff6b6b;
    }
    
    #pullToReloadIndicator .reload-icon {
        display: inline-block;
        font-size: 2.4rem;
        transition: transform 0.3s ease;
        flex-shrink: 0;
    }
    
    #pullToReloadIndicator .reload-icon.spinning {
        animation: spinReload 0.6s linear infinite;
    }
    
    @keyframes spinReload {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    #pullToReloadIndicator .reload-text {
        font-weight: 600;
        letter-spacing: 0.5px;
    }
    
    #pullToReloadIndicator .pull-progress-dot {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: rgba(0, 255, 65, 0.15);
        border: 2px solid rgba(0, 255, 65, 0.3);
        flex-shrink: 0;
        transition: all 0.1s ease;
        position: relative;
    }
    
    #pullToReloadIndicator .pull-progress-dot .dot-fill {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        border-radius: 50%;
        background: var(--accent, #00ff41);
        clip-path: polygon(50% 50%, 50% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%, 50% 0%);
        transform: rotate(-90deg);
        transition: none;
        opacity: 0.3;
    }
    
    #pullToReloadIndicator .pull-progress-dot .percentage-text {
        font-size: 0.65rem;
        font-weight: 700;
        z-index: 1;
        color: var(--accent, #00ff41);
    }
    
    #pullToReloadIndicator.release-ready .pull-progress-dot {
        border-color: #ff6b6b;
        background: rgba(255, 107, 107, 0.15);
        transform: scale(1.1);
    }
    
    #pullToReloadIndicator.release-ready .pull-progress-dot .percentage-text {
        color: #ff6b6b;
    }
    
    #pullToReloadIndicator.release-ready .pull-progress-dot .dot-fill {
        background: #ff6b6b;
        opacity: 0.4;
    }
    
    /* Light mode adjustments */
    @media (prefers-color-scheme: light) {
        #pullToReloadIndicator {
            background: linear-gradient(180deg, rgba(240, 240, 240, 0.95) 0%, rgba(240, 240, 240, 0) 100%);
            color: #1a1a1a;
        }
        #pullToReloadIndicator .pull-progress-dot {
            border-color: rgba(0, 0, 0, 0.2);
            background: rgba(0, 0, 0, 0.05);
        }
        #pullToReloadIndicator .pull-progress-dot .dot-fill {
            background: #00cc33;
        }
        #pullToReloadIndicator .pull-progress-dot .percentage-text {
            color: #00cc33;
        }
        #pullToReloadIndicator.release-ready .pull-progress-dot {
            border-color: #ff6b6b;
            background: rgba(255, 107, 107, 0.1);
        }
        #pullToReloadIndicator.release-ready .pull-progress-dot .percentage-text {
            color: #ff6b6b;
        }
    }
    
    /* Mobile optimization */
    @media (max-width: 600px) {
        #pullToReloadIndicator {
            padding: 12px 0 25px 0;
            font-size: 0.8rem;
            min-height: 50px;
        }
        #pullToReloadIndicator .reload-icon {
            font-size: 2rem;
        }
        #pullToReloadIndicator .pull-progress-dot {
            width: 24px;
            height: 24px;
        }
        #pullToReloadIndicator .pull-progress-dot .percentage-text {
            font-size: 0.55rem;
        }
    }
    
    /* CRITICAL: Lock the body and custom-body */
    html, body {
        overscroll-behavior: none !important;
        overflow: hidden !important;
        height: 100% !important;
        position: fixed !important;
        width: 100% !important;
        top: 0 !important;
        left: 0 !important;
    }
    
    .custom-body {
        overscroll-behavior: contain !important;
        overflow-y: auto !important;
        -webkit-overflow-scrolling: touch !important;
        height: 100% !important;
        width: 100% !important;
        position: relative !important;
    }
    
    /* Prevent any pull-to-refresh on the body */
    body {
        touch-action: none !important;
    }
    
    .custom-body {
        touch-action: pan-y !important;
    }
</style>

<div id="pullToReloadContainer">
    <div id="pullToReloadIndicator">
        <span class="reload-icon">⟳</span>
        <span class="reload-text">Pull to refresh</span>
        <div class="pull-progress-dot">
            <span class="percentage-text">0%</span>
            <div class="dot-fill"></div>
        </div>
    </div>
</div>

<script>
(function() {
    'use strict';
    
    class PullToReload {
        constructor(options = {}) {
            // Configuration with customizable pull distance
            this.config = {
                threshold: 80,
                thresholdPercentage: 30,
                resistance: 0.5,
                maxPullPercentage: 50,
                cooldown: 1000,
                debug: false,
                scrollContainer: '.custom-body',
                usePercentage: true,
                ...options
            };
            
            // DOM elements
            this.container = document.querySelector(this.config.scrollContainer) || document.querySelector('.custom-body') || document.body;
            this.indicator = document.getElementById('pullToReloadIndicator');
            this.reloadIcon = this.indicator?.querySelector('.reload-icon');
            this.reloadText = this.indicator?.querySelector('.reload-text');
            this.progressDot = this.indicator?.querySelector('.pull-progress-dot');
            this.percentageText = this.progressDot?.querySelector('.percentage-text');
            this.dotFill = this.progressDot?.querySelector('.dot-fill');
            
            // State
            this.isPulling = false;
            this.startY = 0;
            this.currentPull = 0;
            this.currentPullPercentage = 0;
            this.isReloading = false;
            this.lastReloadTime = 0;
            this.touchStartY = 0;
            this.isAtTop = true;
            this.lastScrollTop = 0;
            this.isMouseDown = false;
            this.viewportHeight = window.innerHeight;
            this.thresholdPixels = 0;
            this.isLocked = false;
            this.originalBodyOverflow = '';
            
            // Calculate threshold in pixels based on percentage
            this.calculateThresholds();
            
            // Lock the body initially
            this.lockBody();
            
            // Bind methods
            this.handleScroll = this.handleScroll.bind(this);
            this.handleTouchStart = this.handleTouchStart.bind(this);
            this.handleTouchMove = this.handleTouchMove.bind(this);
            this.handleTouchEnd = this.handleTouchEnd.bind(this);
            this.handleMouseDown = this.handleMouseDown.bind(this);
            this.handleMouseMove = this.handleMouseMove.bind(this);
            this.handleMouseUp = this.handleMouseUp.bind(this);
            this.handleResize = this.handleResize.bind(this);
            
            // Initialize
            this.init();
        }
        
        lockBody() {
            if (!this.isLocked) {
                this.originalBodyOverflow = document.body.style.overflow;
                document.body.style.overflow = 'hidden';
                document.body.style.position = 'fixed';
                document.body.style.width = '100%';
                document.body.style.height = '100%';
                document.body.style.top = '0';
                document.body.style.left = '0';
                document.body.style.overscrollBehavior = 'none';
                document.documentElement.style.overflow = 'hidden';
                document.documentElement.style.position = 'fixed';
                document.documentElement.style.width = '100%';
                document.documentElement.style.height = '100%';
                document.documentElement.style.top = '0';
                document.documentElement.style.left = '0';
                document.documentElement.style.overscrollBehavior = 'none';
                
                // Ensure custom-body can still scroll
                if (this.container) {
                    this.container.style.overscrollBehavior = 'contain';
                    this.container.style.overflowY = 'auto';
                    this.container.style.height = '100%';
                }
                
                this.isLocked = true;
                if (this.config.debug) console.log('Body locked for pull-to-refresh');
            }
        }
        
        unlockBody() {
            if (this.isLocked) {
                document.body.style.overflow = this.originalBodyOverflow || '';
                document.body.style.position = '';
                document.body.style.width = '';
                document.body.style.height = '';
                document.body.style.top = '';
                document.body.style.left = '';
                document.body.style.overscrollBehavior = '';
                document.documentElement.style.overflow = '';
                document.documentElement.style.position = '';
                document.documentElement.style.width = '';
                document.documentElement.style.height = '';
                document.documentElement.style.top = '';
                document.documentElement.style.left = '';
                document.documentElement.style.overscrollBehavior = '';
                
                if (this.container) {
                    this.container.style.overscrollBehavior = '';
                    this.container.style.overflowY = '';
                    this.container.style.height = '';
                }
                
                this.isLocked = false;
                if (this.config.debug) console.log('Body unlocked');
            }
        }
        
        calculateThresholds() {
            this.viewportHeight = window.innerHeight;
            this.thresholdPixels = (this.viewportHeight * this.config.thresholdPercentage) / 100;
            
            if (this.config.usePercentage) {
                this.config.threshold = this.thresholdPixels;
            }
            
            if (this.config.debug) {
                console.log(`Threshold: ${this.config.threshold}px (${this.config.thresholdPercentage}% of viewport)`);
                console.log(`Max Pull: ${(this.viewportHeight * this.config.maxPullPercentage) / 100}px (${this.config.maxPullPercentage}%)`);
            }
        }
        
        init() {
            if (!this.indicator) {
                console.warn('PullToReload: Indicator element not found');
                return;
            }
            
            // Add event listeners to container only
            this.container.addEventListener('scroll', this.handleScroll, { passive: true });
            this.container.addEventListener('touchstart', this.handleTouchStart, { passive: false });
            this.container.addEventListener('touchmove', this.handleTouchMove, { passive: false });
            this.container.addEventListener('touchend', this.handleTouchEnd, { passive: true });
            
            // Mouse events (desktop) - only on container
            this.container.addEventListener('mousedown', this.handleMouseDown);
            document.addEventListener('mousemove', this.handleMouseMove);
            document.addEventListener('mouseup', this.handleMouseUp);
            
            // Window resize
            window.addEventListener('resize', this.handleResize);
            
            // Check initial scroll position
            this.checkScrollPosition();
            
            // Prevent body from scrolling on touch
            document.addEventListener('touchmove', this.preventBodyScroll, { passive: false });
            
            if (this.config.debug) {
                console.log('PullToReload initialized with percentage-based pulling');
            }
        }
        
        preventBodyScroll(e) {
            // Only prevent if we're pulling and not on the container
            if (this.isPulling) {
                e.preventDefault();
            }
        }
        
        handleResize() {
            this.calculateThresholds();
        }
        
        checkScrollPosition() {
            const scrollTop = this.container.scrollTop || window.pageYOffset || document.documentElement.scrollTop;
            this.isAtTop = scrollTop <= 0;
            this.lastScrollTop = scrollTop;
        }
        
        handleScroll() {
            const scrollTop = this.container.scrollTop || window.pageYOffset || document.documentElement.scrollTop;
            this.isAtTop = scrollTop <= 0;
            this.lastScrollTop = scrollTop;
        }
        
        handleTouchStart(e) {
            if (this.isReloading) return;
            
            const touch = e.touches[0];
            this.touchStartY = touch.clientY;
            this.isPulling = false;
            
            // Check if at top of container
            const scrollTop = this.container.scrollTop || 0;
            this.isAtTop = scrollTop <= 0;
            
            if (!this.isAtTop) {
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
        }
        
        handleTouchMove(e) {
            if (this.isReloading) return;
            
            const touch = e.touches[0];
            const deltaY = touch.clientY - this.touchStartY;
            
            // Only allow pull down
            if (deltaY <= 0) {
                if (this.isPulling) {
                    this.isPulling = false;
                    this.currentPull = 0;
                    this.currentPullPercentage = 0;
                    this.updateIndicator(0);
                }
                return;
            }
            
            // Check if at top of container
            const scrollTop = this.container.scrollTop || 0;
            this.isAtTop = scrollTop <= 0;
            
            if (!this.isAtTop) {
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
            
            // Calculate pull distance with resistance
            const rawPull = deltaY;
            const resistedPull = rawPull * this.config.resistance;
            
            // Calculate max pull in pixels based on percentage
            const maxPullPixels = (this.viewportHeight * this.config.maxPullPercentage) / 100;
            this.currentPull = Math.min(resistedPull, maxPullPixels);
            
            // Calculate percentage of viewport height pulled
            this.currentPullPercentage = (this.currentPull / this.viewportHeight) * 100;
            
            this.isPulling = this.currentPull > 5;
            
            // Update indicator instantly
            this.updateIndicator(this.currentPull);
            
            // ALWAYS prevent default when pulling
            e.preventDefault();
        }
        
        handleTouchEnd(e) {
            if (this.isReloading || !this.isPulling) {
                this.isPulling = false;
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
            
            // Check if threshold reached
            if (this.currentPull >= this.config.threshold) {
                this.triggerReload();
            } else {
                // Reset with animation
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                this.isPulling = false;
            }
        }
        
        handleMouseDown(e) {
            if (this.isReloading) return;
            
            // Only left click
            if (e.button !== 0) return;
            
            // Check if at top of container
            const scrollTop = this.container.scrollTop || 0;
            this.isAtTop = scrollTop <= 0;
            
            if (!this.isAtTop) {
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
            
            this.isMouseDown = true;
            this.startY = e.clientY;
            this.isPulling = false;
        }
        
        handleMouseMove(e) {
            if (!this.isMouseDown || this.isReloading) return;
            
            const deltaY = e.clientY - this.startY;
            
            // Only allow pull down
            if (deltaY <= 0) {
                if (this.isPulling) {
                    this.isPulling = false;
                    this.currentPull = 0;
                    this.currentPullPercentage = 0;
                    this.updateIndicator(0);
                }
                return;
            }
            
            // Check if at top of container
            const scrollTop = this.container.scrollTop || 0;
            this.isAtTop = scrollTop <= 0;
            
            if (!this.isAtTop) {
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
            
            // Calculate pull distance with resistance
            const rawPull = deltaY;
            const resistedPull = rawPull * this.config.resistance;
            
            // Calculate max pull in pixels based on percentage
            const maxPullPixels = (this.viewportHeight * this.config.maxPullPercentage) / 100;
            this.currentPull = Math.min(resistedPull, maxPullPixels);
            
            // Calculate percentage of viewport height pulled
            this.currentPullPercentage = (this.currentPull / this.viewportHeight) * 100;
            
            this.isPulling = this.currentPull > 5;
            
            // Update indicator instantly
            this.updateIndicator(this.currentPull);
        }
        
        handleMouseUp(e) {
            if (!this.isMouseDown) return;
            this.isMouseDown = false;
            
            if (this.isReloading || !this.isPulling) {
                this.isPulling = false;
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                return;
            }
            
            // Check if threshold reached
            if (this.currentPull >= this.config.threshold) {
                this.triggerReload();
            } else {
                // Reset with animation
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                this.isPulling = false;
            }
        }
        
        updateIndicator(pullDistance) {
            if (!this.indicator) return;
            
            // Update position instantly (no transition)
            const maxPullPixels = (this.viewportHeight * this.config.maxPullPercentage) / 100;
            const percentage = maxPullPixels > 0 ? Math.min(pullDistance / maxPullPixels, 1) : 0;
            const translateY = -100 + (percentage * 100);
            
            // Apply transform instantly
            this.indicator.style.transform = `translateY(${translateY}%)`;
            
            // Show/hide based on pull
            if (pullDistance > 5) {
                this.indicator.classList.add('visible');
            } else {
                this.indicator.classList.remove('visible');
                this.indicator.classList.remove('release-ready');
            }
            
            // Update progress dot
            if (this.percentageText) {
                const percent = Math.min((pullDistance / this.viewportHeight) * 100, this.config.maxPullPercentage);
                this.percentageText.textContent = `${Math.round(percent)}%`;
            }
            
            // Update dot fill (circular progress)
            if (this.dotFill) {
                const progress = Math.min((pullDistance / this.config.threshold) * 100, 100);
                const degrees = (progress / 100) * 360;
                this.dotFill.style.clipPath = `polygon(50% 50%, 50% 0%, ${50 + 50 * Math.sin(degrees * Math.PI / 180)}% ${50 - 50 * Math.cos(degrees * Math.PI / 180)}%`;
                
                // Complete circle if progress >= 100%
                if (progress >= 100) {
                    this.dotFill.style.clipPath = `polygon(50% 50%, 50% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%, 50% 0%)`;
                }
            }
            
            // Update text and icon based on pull distance
            if (pullDistance >= this.config.threshold) {
                this.indicator.classList.add('release-ready');
                if (this.reloadText) {
                    this.reloadText.textContent = 'Release to refresh';
                }
                if (this.reloadIcon) {
                    this.reloadIcon.style.transform = 'rotate(180deg)';
                }
            } else {
                this.indicator.classList.remove('release-ready');
                if (this.reloadText) {
                    this.reloadText.textContent = 'Pull to refresh';
                }
                if (this.reloadIcon) {
                    this.reloadIcon.style.transform = `rotate(${pullDistance * 1.5}deg)`;
                }
            }
        }
        
        triggerReload() {
            if (this.isReloading) return;
            
            // Check cooldown
            const now = Date.now();
            if (now - this.lastReloadTime < this.config.cooldown) {
                if (this.config.debug) {
                    console.log('PullToReload: Cooldown active');
                }
                this.currentPull = 0;
                this.currentPullPercentage = 0;
                this.updateIndicator(0);
                this.isPulling = false;
                return;
            }
            
            this.isReloading = true;
            this.lastReloadTime = now;
            
            // Update indicator to show loading state
            if (this.reloadText) {
                this.reloadText.textContent = 'Refreshing...';
            }
            if (this.reloadIcon) {
                this.reloadIcon.classList.add('spinning');
            }
            if (this.progressDot) {
                this.progressDot.style.display = 'none';
            }
            if (this.indicator) {
                this.indicator.style.transform = 'translateY(0%)';
                this.indicator.classList.add('visible');
                this.indicator.classList.remove('release-ready');
            }
            
            if (this.config.debug) {
                console.log('PullToReload: Triggering reload');
            }
            
            // Show loading overlay
            if (window.loadingManager) {
                window.loadingManager.show();
                window.loadingManager.isComplete = false;
            }
            
            // Perform reload
            this.performReload();
        }
        
        performReload() {
            // Unlock body before reload
            this.unlockBody();
            
            // Reload the page
            window.location.reload();
            
            // Fallback: if page doesn't reload (e.g., SPA), reset after timeout
            setTimeout(() => {
                this.resetReload();
            }, 5000);
        }
        
        resetReload() {
            this.isReloading = false;
            this.currentPull = 0;
            this.currentPullPercentage = 0;
            this.isPulling = false;
            
            if (this.reloadText) {
                this.reloadText.textContent = 'Pull to refresh';
            }
            if (this.reloadIcon) {
                this.reloadIcon.classList.remove('spinning');
                this.reloadIcon.style.transform = 'rotate(0deg)';
            }
            if (this.progressDot) {
                this.progressDot.style.display = 'flex';
            }
            
            this.updateIndicator(0);
            
            if (this.indicator) {
                this.indicator.classList.remove('visible');
                this.indicator.style.transform = 'translateY(-100%)';
            }
            
            this.unlockBody();
            
            if (this.config.debug) {
                console.log('PullToReload: Reset complete');
            }
        }
        
        // Public method to manually trigger refresh
        refresh() {
            this.triggerReload();
        }
        
        // Public method to update configuration
        updateConfig(options) {
            Object.assign(this.config, options);
            this.calculateThresholds();
            if (this.config.debug) {
                console.log('Config updated:', this.config);
            }
        }
        
        // Clean up event listeners
        destroy() {
            this.unlockBody();
            this.container.removeEventListener('scroll', this.handleScroll);
            this.container.removeEventListener('touchstart', this.handleTouchStart);
            this.container.removeEventListener('touchmove', this.handleTouchMove);
            this.container.removeEventListener('touchend', this.handleTouchEnd);
            this.container.removeEventListener('mousedown', this.handleMouseDown);
            document.removeEventListener('mousemove', this.handleMouseMove);
            document.removeEventListener('mouseup', this.handleMouseUp);
            window.removeEventListener('resize', this.handleResize);
            document.removeEventListener('touchmove', this.preventBodyScroll);
        }
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.pullToReload = new PullToReload({
                threshold: 20,
                thresholdPercentage: 30,
                resistance: 1,
                maxPullPercentage: 30,
                cooldown: 1000,
                debug: false,
                usePercentage: true,
                scrollContainer: '.custom-body'
            });
        });
    } else {
        window.pullToReload = new PullToReload({
            threshold: 20,
            thresholdPercentage: 30,
            resistance: 1,
            maxPullPercentage: 30,
            cooldown: 1000,
            debug: false,
            usePercentage: true,
            scrollContainer: '.custom-body'
        });
    }
    
})();
</script>