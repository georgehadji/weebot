// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Navbar background on scroll
const navbar = document.querySelector('.navbar');
let lastScroll = 0;

window.addEventListener('scroll', () => {
    const currentScroll = window.pageYOffset;
    
    if (currentScroll > 50) {
        navbar.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.1)';
    } else {
        navbar.style.boxShadow = 'none';
    }
    
    lastScroll = currentScroll;
});

// Parallax effect for hero orbs
const heroOrbs = document.querySelectorAll('.hero-orb');
let ticking = false;

window.addEventListener('scroll', () => {
    if (!ticking) {
        window.requestAnimationFrame(() => {
            const scrolled = window.pageYOffset;
            const heroSection = document.querySelector('.hero');
            
            if (heroSection) {
                const heroRect = heroSection.getBoundingClientRect();
                if (heroRect.bottom > 0) {
                    heroOrbs.forEach((orb, index) => {
                        const speed = 0.1 + (index * 0.05);
                        const yPos = -(scrolled * speed);
                        orb.style.transform = `translateY(${yPos}px)`;
                    });
                }
            }
            ticking = false;
        });
        ticking = true;
    }
});

// Mouse move effect for floating cards
const floatingCards = document.querySelectorAll('.floating-card');
const heroVisual = document.querySelector('.hero-visual');

if (heroVisual && floatingCards.length > 0) {
    heroVisual.addEventListener('mousemove', (e) => {
        const rect = heroVisual.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        
        const deltaX = (x - centerX) / centerX;
        const deltaY = (y - centerY) / centerY;
        
        floatingCards.forEach((card, index) => {
            const intensity = 10 + (index * 5);
            const moveX = deltaX * intensity;
            const moveY = deltaY * intensity;
            
            card.style.transform = `translate(${moveX}px, ${moveY}px)`;
        });
    });
    
    heroVisual.addEventListener('mouseleave', () => {
        floatingCards.forEach(card => {
            card.style.transform = 'translate(0, 0)';
            card.style.transition = 'transform 0.5s ease-out';
        });
    });
}

// Intersection Observer for fade-in animations
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -100px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Apply fade-in animation to feature cards
document.querySelectorAll('.feature-card').forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(30px)';
    card.style.transition = `all 0.6s ease ${index * 0.1}s`;
    observer.observe(card);
});

// Add hover effect enhancement for buttons
document.querySelectorAll('.btn').forEach(button => {
    button.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-2px)';
    });
    
    button.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0)';
    });
});

// Typing effect for code window (optional enhancement)
const codeLines = document.querySelectorAll('.code-line');
if (codeLines.length > 0) {
    codeLines.forEach((line, index) => {
        line.style.opacity = '0';
        setTimeout(() => {
            line.style.opacity = '1';
        }, 500 + (index * 100));
    });
}

// Mobile menu toggle with enhanced animations
const createMobileMenu = () => {
    const menuToggle = document.createElement('button');
    menuToggle.className = 'mobile-menu-toggle';
    menuToggle.setAttribute('aria-label', 'Toggle menu');
    menuToggle.setAttribute('aria-expanded', 'false');
    menuToggle.innerHTML = '<span class="hamburger-line"></span><span class="hamburger-line"></span><span class="hamburger-line"></span>';
    menuToggle.style.display = 'none';
    
    // Add enhanced mobile menu styles
    const style = document.createElement('style');
    style.textContent = `
        @media (max-width: 768px) {
            .mobile-menu-toggle {
                display: flex !important;
                flex-direction: column;
                justify-content: space-around;
                width: 30px;
                height: 25px;
                background: none;
                border: none;
                cursor: pointer;
                padding: 0;
                z-index: 1001;
            }
            
            .hamburger-line {
                width: 100%;
                height: 3px;
                background: var(--primary-dark);
                border-radius: 2px;
                transition: all 0.3s ease;
            }
            
            .mobile-menu-toggle.active .hamburger-line:nth-child(1) {
                transform: translateY(11px) rotate(45deg);
            }
            
            .mobile-menu-toggle.active .hamburger-line:nth-child(2) {
                opacity: 0;
            }
            
            .mobile-menu-toggle.active .hamburger-line:nth-child(3) {
                transform: translateY(-11px) rotate(-45deg);
            }
            
            .nav-menu {
                position: fixed;
                top: 70px;
                left: -100%;
                width: 100%;
                height: calc(100vh - 70px);
                background: white;
                flex-direction: column;
                padding: 40px 20px;
                transition: left 0.3s ease;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
                overflow-y: auto;
            }
            
            .nav-menu.active {
                left: 0;
            }
            
            .nav-menu li {
                margin: 20px 0;
                opacity: 0;
                transform: translateX(-20px);
                transition: all 0.3s ease;
            }
            
            .nav-menu.active li {
                opacity: 1;
                transform: translateX(0);
            }
            
            .nav-menu.active li:nth-child(1) { transition-delay: 0.1s; }
            .nav-menu.active li:nth-child(2) { transition-delay: 0.15s; }
            .nav-menu.active li:nth-child(3) { transition-delay: 0.2s; }
            .nav-menu.active li:nth-child(4) { transition-delay: 0.25s; }
            .nav-menu.active li:nth-child(5) { transition-delay: 0.3s; }
        }
    `;
    document.head.appendChild(style);
    
    const navContent = document.querySelector('.nav-content');
    const navMenu = document.querySelector('.nav-menu');
    
    if (navContent && navMenu) {
        navContent.insertBefore(menuToggle, navMenu);
        
        menuToggle.addEventListener('click', () => {
            const isActive = navMenu.classList.toggle('active');
            menuToggle.classList.toggle('active');
            menuToggle.setAttribute('aria-expanded', isActive);
            
            // Prevent body scroll when menu is open
            document.body.style.overflow = isActive ? 'hidden' : '';
        });
        
        // Close menu when clicking on a link
        navMenu.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                navMenu.classList.remove('active');
                menuToggle.classList.remove('active');
                menuToggle.setAttribute('aria-expanded', 'false');
                document.body.style.overflow = '';
            });
        });
    }
};

// Initialize mobile menu
createMobileMenu();

// Showcase code tabs functionality
const showcaseCodeTabs = document.querySelectorAll('.showcase-code-tab');
const showcaseCodePanes = document.querySelectorAll('.showcase-code-pane');

showcaseCodeTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const lang = tab.getAttribute('data-lang');
        
        // Remove active class from all tabs and panes
        showcaseCodeTabs.forEach(t => t.classList.remove('showcase-code-tab--active'));
        showcaseCodePanes.forEach(p => p.classList.remove('showcase-code-pane--active'));
        
        // Add active class to clicked tab and corresponding pane
        tab.classList.add('showcase-code-tab--active');
        const activePane = document.querySelector(`.showcase-code-pane[data-lang="${lang}"]`);
        if (activePane) {
            activePane.classList.add('showcase-code-pane--active');
        }
    });
});

// Intersection Observer for showcase rows
const showcaseObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, {
    threshold: 0.1,
    rootMargin: '0px 0px -100px 0px'
});

// Apply fade-in animation to showcase rows
document.querySelectorAll('.showcase-row').forEach((row, index) => {
    row.style.opacity = '0';
    row.style.transform = 'translateY(40px)';
    row.style.transition = `all 0.8s ease ${index * 0.2}s`;
    showcaseObserver.observe(row);
});

// Animate dashboard stats on scroll
const dashboardStats = document.querySelectorAll('.dashboard-stat');
const dashboardObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const stats = entry.target.querySelectorAll('.dashboard-stat');
            stats.forEach((stat, index) => {
                setTimeout(() => {
                    stat.style.opacity = '1';
                    stat.style.transform = 'translateY(0)';
                }, index * 100);
            });
        }
    });
}, {
    threshold: 0.3
});

const dashboardMockup = document.querySelector('.dashboard-mockup');
if (dashboardMockup) {
    dashboardStats.forEach(stat => {
        stat.style.opacity = '0';
        stat.style.transform = 'translateY(20px)';
        stat.style.transition = 'all 0.5s ease';
    });
    dashboardObserver.observe(dashboardMockup);
}

// Animate transactions on scroll
const transactions = document.querySelectorAll('.dashboard-transaction');
const transactionsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const txns = entry.target.querySelectorAll('.dashboard-transaction');
            txns.forEach((txn, index) => {
                setTimeout(() => {
                    txn.style.opacity = '1';
                    txn.style.transform = 'translateX(0)';
                }, index * 150);
            });
        }
    });
}, {
    threshold: 0.3
});

const transactionsContainer = document.querySelector('.dashboard-transactions');
if (transactionsContainer) {
    transactions.forEach(txn => {
        txn.style.opacity = '0';
        txn.style.transform = 'translateX(-20px)';
        txn.style.transition = 'all 0.5s ease';
    });
    transactionsObserver.observe(transactionsContainer);
}

// ============================================
// Scroll Progress Indicator
// ============================================
const createScrollProgress = () => {
    const progressBar = document.createElement('div');
    progressBar.className = 'scroll-progress';
    progressBar.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        height: 3px;
        background: linear-gradient(90deg, #0066ff 0%, #00d9ff 100%);
        width: 0%;
        z-index: 9999;
        transition: width 0.1s ease;
    `;
    document.body.appendChild(progressBar);
    
    window.addEventListener('scroll', () => {
        const windowHeight = document.documentElement.scrollHeight - document.documentElement.clientHeight;
        const scrolled = (window.pageYOffset / windowHeight) * 100;
        progressBar.style.width = scrolled + '%';
    });
};

createScrollProgress();

// ============================================
// Scroll to Top Button
// ============================================
const createScrollToTop = () => {
    const scrollButton = document.createElement('button');
    scrollButton.className = 'scroll-to-top';
    scrollButton.setAttribute('aria-label', 'Scroll to top');
    scrollButton.innerHTML = '↑';
    scrollButton.style.cssText = `
        position: fixed;
        bottom: 30px;
        right: 30px;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: linear-gradient(135deg, #635bff 0%, #00d4ff 100%);
        color: white;
        border: none;
        font-size: 24px;
        cursor: pointer;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(99, 91, 255, 0.3);
        z-index: 1000;
    `;
    
    document.body.appendChild(scrollButton);
    
    window.addEventListener('scroll', () => {
        if (window.pageYOffset > 300) {
            scrollButton.style.opacity = '1';
            scrollButton.style.visibility = 'visible';
        } else {
            scrollButton.style.opacity = '0';
            scrollButton.style.visibility = 'hidden';
        }
    });
    
    scrollButton.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
    
    scrollButton.addEventListener('mouseenter', () => {
        scrollButton.style.transform = 'translateY(-5px)';
        scrollButton.style.boxShadow = '0 6px 20px rgba(99, 91, 255, 0.4)';
    });
    
    scrollButton.addEventListener('mouseleave', () => {
        scrollButton.style.transform = 'translateY(0)';
        scrollButton.style.boxShadow = '0 4px 15px rgba(99, 91, 255, 0.3)';
    });
};

createScrollToTop();

// ============================================
// Enhanced Keyboard Navigation
// ============================================
document.addEventListener('keydown', (e) => {
    // ESC key closes mobile menu
    if (e.key === 'Escape') {
        const navMenu = document.querySelector('.nav-menu');
        const menuToggle = document.querySelector('.mobile-menu-toggle');
        if (navMenu && navMenu.classList.contains('active')) {
            navMenu.classList.remove('active');
            if (menuToggle) {
                menuToggle.classList.remove('active');
                menuToggle.setAttribute('aria-expanded', 'false');
            }
            document.body.style.overflow = '';
        }
    }
    
    // Tab key focus management for better accessibility
    if (e.key === 'Tab') {
        document.body.classList.add('keyboard-navigation');
    }
});

document.addEventListener('mousedown', () => {
    document.body.classList.remove('keyboard-navigation');
});

// Add focus styles for keyboard navigation
const focusStyle = document.createElement('style');
focusStyle.textContent = `
    body.keyboard-navigation *:focus {
        outline: 2px solid #635bff !important;
        outline-offset: 2px;
    }
    
    body:not(.keyboard-navigation) *:focus {
        outline: none;
    }
`;
document.head.appendChild(focusStyle);

// ============================================
// Lazy Loading for Images
// ============================================
const lazyLoadImages = () => {
    const images = document.querySelectorAll('img[data-src]');
    
    const imageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.getAttribute('data-src');
                img.removeAttribute('data-src');
                img.classList.add('loaded');
                imageObserver.unobserve(img);
            }
        });
    }, {
        rootMargin: '50px 0px',
        threshold: 0.01
    });
    
    images.forEach(img => imageObserver.observe(img));
};

lazyLoadImages();

// ============================================
// Form Validation (if forms exist)
// ============================================
const forms = document.querySelectorAll('form');
forms.forEach(form => {
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const inputs = form.querySelectorAll('input[required], textarea[required]');
        let isValid = true;
        
        inputs.forEach(input => {
            if (!input.value.trim()) {
                isValid = false;
                input.style.borderColor = '#ff4444';
                input.style.animation = 'shake 0.3s ease';
                
                setTimeout(() => {
                    input.style.animation = '';
                }, 300);
            } else {
                input.style.borderColor = '';
            }
            
            // Email validation
            if (input.type === 'email' && input.value) {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRegex.test(input.value)) {
                    isValid = false;
                    input.style.borderColor = '#ff4444';
                }
            }
        });
        
        if (isValid) {
            // Show success message
            const successMsg = document.createElement('div');
            successMsg.textContent = '✓ Thank you! We\'ll be in touch soon.';
            successMsg.style.cssText = `
                padding: 15px;
                background: #00d924;
                color: white;
                border-radius: 8px;
                margin-top: 15px;
                text-align: center;
                animation: slideIn 0.3s ease;
            `;
            form.appendChild(successMsg);
            form.reset();
            
            setTimeout(() => {
                successMsg.remove();
            }, 5000);
        }
    });
});

// Add shake animation for form validation
const formStyle = document.createElement('style');
formStyle.textContent = `
    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-10px); }
        75% { transform: translateX(10px); }
    }
    
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
`;
document.head.appendChild(formStyle);

// ============================================
// Enhanced Button Ripple Effect
// ============================================
document.querySelectorAll('.btn').forEach(button => {
    button.addEventListener('click', function(e) {
        const ripple = document.createElement('span');
        const rect = this.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = e.clientX - rect.left - size / 2;
        const y = e.clientY - rect.top - size / 2;
        
        ripple.style.cssText = `
            position: absolute;
            width: ${size}px;
            height: ${size}px;
            left: ${x}px;
            top: ${y}px;
            background: rgba(255, 255, 255, 0.5);
            border-radius: 50%;
            transform: scale(0);
            animation: ripple 0.6s ease-out;
            pointer-events: none;
        `;
        
        this.style.position = 'relative';
        this.style.overflow = 'hidden';
        this.appendChild(ripple);
        
        setTimeout(() => ripple.remove(), 600);
    });
});

// Add ripple animation
const rippleStyle = document.createElement('style');
rippleStyle.textContent = `
    @keyframes ripple {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
`;
document.head.appendChild(rippleStyle);

// ============================================
// Performance: Debounce scroll events
// ============================================
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Console message for developers
console.log('%c🚀 Stripe Landing Page', 'font-size: 20px; font-weight: bold; color: #635bff;');
console.log('%cBuilt with modern web technologies', 'font-size: 14px; color: #425466;');
console.log('%c✨ Features: Animated mesh gradient, parallax effects, interactive code window, product showcase with dashboard mockup', 'font-size: 12px; color: #00d4ff;');
console.log('%c🎯 Enhanced: Scroll animations, mobile menu, smooth scrolling, keyboard navigation, form validation', 'font-size: 12px; color: #00d924;');

// ============================================
// Stats Section: Animated Counters + Live Ticker
// ============================================

// Easing function for smooth counter animation
function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
}

// Animate a single counter from 0 to target
function animateCounter(element, target, decimals, duration) {
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easedProgress = easeOutExpo(progress);
        const currentValue = easedProgress * target;

        if (decimals > 0) {
            element.textContent = currentValue.toFixed(decimals);
        } else {
            element.textContent = Math.floor(currentValue).toLocaleString();
        }

        if (progress < 1) {
            requestAnimationFrame(update);
        } else {
            // Ensure final value is exact
            if (decimals > 0) {
                element.textContent = target.toFixed(decimals);
            } else {
                element.textContent = target.toLocaleString();
            }
        }
    }

    requestAnimationFrame(update);
}

// Intersection Observer for stats section
const statsSection = document.querySelector('.stats');
const statCards = document.querySelectorAll('.stat-card');
const statCounters = document.querySelectorAll('.stat-counter');
let statsAnimated = false;

const statsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting && !statsAnimated) {
            statsAnimated = true;

            // Animate each card with staggered delay
            statCards.forEach((card, index) => {
                setTimeout(() => {
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0)';
                    card.classList.add('animated');

                    // Animate the counter inside this card
                    const counter = card.querySelector('.stat-counter');
                    if (counter) {
                        const target = parseFloat(counter.getAttribute('data-target'));
                        const decimals = parseInt(counter.getAttribute('data-decimals')) || 0;
                        animateCounter(counter, target, decimals, 2000);
                    }
                }, index * 150);
            });
        }
    });
}, {
    threshold: 0.2,
    rootMargin: '0px 0px -50px 0px'
});

// Set initial state for stat cards
statCards.forEach(card => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(30px)';
    card.style.transition = 'all 0.7s cubic-bezier(0.4, 0, 0.2, 1)';
});

if (statsSection) {
    statsObserver.observe(statsSection);
}

// Live ticker: simulate real-time processing amount
const liveCounter = document.getElementById('liveCounter');
if (liveCounter) {
    // Base amount per second (~$31,700 based on $1T/year)
    const basePerSecond = 31700;
    let currentAmount = basePerSecond;

    function updateLiveCounter() {
        // Add some realistic variance (±15%)
        const variance = 1 + (Math.random() * 0.3 - 0.15);
        currentAmount = Math.round(basePerSecond * variance);
        liveCounter.textContent = '$' + currentAmount.toLocaleString();
    }

    // Initial update
    updateLiveCounter();

    // Update every 1.5 seconds for a dynamic feel
    setInterval(updateLiveCounter, 1500);
}
