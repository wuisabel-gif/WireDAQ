/**
 * Elysian Theme JavaScript
 * Handles dark mode, reveal animations, mobile menu, and publication search
 */

// Define global functions first
window.toggleDarkMode = function() { 
    document.documentElement.classList.toggle('dark'); 
    localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light'; 
    updateThemeIcon();
};

window.updateThemeIcon = function() {
    const icon = document.getElementById('theme-icon');
    if (icon) {
        const isDark = document.documentElement.classList.contains('dark');
        icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    }
};

window.toggleMobileMenu = function() {
    const menu = document.getElementById('mobile-menu');
    menu.classList.toggle('opacity-0');
    menu.classList.toggle('invisible');
};

window.copyBibtex = function(button) {
   const bibtex = button.getAttribute('data-bibtex');
   if (navigator.clipboard && bibtex && !button.disabled) {
       navigator.clipboard.writeText(bibtex).then(() => {
           const originalText = button.innerHTML;
           button.disabled = true;
           button.innerHTML = '<i class="fas fa-check"></i> Copied!';
           button.classList.add('cite-copied');
           setTimeout(() => {
               button.innerHTML = originalText;
               button.classList.remove('cite-copied');
               button.disabled = false;
           }, 2000);
       });
   }
};

// Immediately set dark mode to prevent flashing
if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
} else {
    document.documentElement.classList.remove('dark');
}

document.addEventListener('DOMContentLoaded', () => {
    document.documentElement.classList.add('js-enabled');
    
    // Set initial theme icon based on current dark mode state
    updateThemeIcon();
    
    // More robust reveal system - elements reveal immediately if they're above fold or on scroll
    function revealElement(el) {
        const rect = el.getBoundingClientRect();
        const windowHeight = window.innerHeight;
        // Reveal if element is in viewport or close to it (within 200px)
        if (rect.top < windowHeight + 200) {
            el.classList.add('active');
        }
    }
    
    // Initial check for elements already in viewport
    document.querySelectorAll('.reveal').forEach(revealElement);
    
    // Backup: reveal all elements after a short delay to prevent stuck content
    setTimeout(() => {
        document.querySelectorAll('.reveal:not(.active)').forEach(el => el.classList.add('active'));
    }, 1000);
    
    // Also observe for scroll-based reveals
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => { if (entry.isIntersecting) entry.target.classList.add('active'); });
    }, { threshold: 0.1, rootMargin: '50px' });
    document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
    
    // Scroll-triggered divider animations
    const dividerObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('divider-visible');
            }
        });
    }, { 
        threshold: 0.3, // Trigger when 30% of divider is visible
        rootMargin: '0px 0px -10% 0px' // Trigger slightly before reaching bottom of viewport
    });
    
    // Observe all elysian dividers
    document.querySelectorAll('.elysian-divider').forEach(divider => {
        dividerObserver.observe(divider);
    });
    
    // Project card follow-focus effect
    function initProjectCardEffects() {
        const projectCards = document.querySelectorAll('.project-card');
        
        projectCards.forEach(card => {
            const image = card.querySelector('.project-image');
            if (!image) return; // Skip cards without images
            
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const x = (e.clientX - rect.left) / rect.width;
                const y = (e.clientY - rect.top) / rect.height;
                
                // Clamp values between 0 and 1
                const clampedX = Math.max(0, Math.min(1, x));
                const clampedY = Math.max(0, Math.min(1, y));
                
                card.style.setProperty('--mouse-x', clampedX);
                card.style.setProperty('--mouse-y', clampedY);
            });
            
            card.addEventListener('mouseleave', () => {
                // Reset to center position
                card.style.setProperty('--mouse-x', 0.5);
                card.style.setProperty('--mouse-y', 0.5);
            });
        });
    }
    
    // Initialize project card effects
    initProjectCardEffects();
    
    // Reading progress bar for blog posts
    initReadingProgress();
});

// ============================================================================
// READING PROGRESS BAR
// ============================================================================

/**
 * Reading Progress Bar
 * Shows progress through blog post content
 */
function initReadingProgress() {
    // Only run on pages with main prose content (blog posts, pages)
    const blogContent = document.querySelector('.prose-main');
    if (!blogContent) return;
    
    // Create progress bar element
    const progressBar = document.createElement('div');
    progressBar.className = 'reading-progress';
    progressBar.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #14b8a6, #10b981);
        transform-origin: left;
        transform: scaleX(0);
        z-index: 100;
        transition: transform 0.1s ease-out;
    `;
    document.body.appendChild(progressBar);
    
    // Update progress on scroll
    function updateProgress() {
        const windowHeight = window.innerHeight;
        const documentHeight = document.documentElement.scrollHeight - windowHeight;
        const scrolled = window.scrollY;
        const progress = Math.min(Math.max(scrolled / documentHeight, 0), 1);
        progressBar.style.transform = `scaleX(${progress})`;
    }
    
    window.addEventListener('scroll', updateProgress, { passive: true });
    updateProgress(); // Initial update
}

// Simple search-only functionality - let server handle grouping/sorting
if (document.title.includes('Publications')) {
    document.addEventListener('DOMContentLoaded', function() {
        const searchInput = document.getElementById('search-input');
        if (!searchInput) return; // Only run if search input exists
        
        // Get all publication items once
        const allPublications = document.querySelectorAll('[data-pub-item]');
        
        // Simple search function
        function filterPublications(searchTerm) {
            const searchLower = searchTerm.toLowerCase().trim();
            
            allPublications.forEach(item => {
                const searchText = item.textContent.toLowerCase();
                const parentGroup = item.closest('[data-group]');
                
                if (!searchTerm || searchText.includes(searchLower)) {
                    // Show item and its parent group
                    item.style.display = '';
                    if (parentGroup) parentGroup.style.display = '';
                } else {
                    // Hide item
                    item.style.display = 'none';
                }
            });
            
            // Hide empty year groups
            document.querySelectorAll('[data-group]').forEach(group => {
                const visibleItems = group.querySelectorAll('[data-pub-item]:not([style*="display: none"])');
                group.style.display = visibleItems.length > 0 ? '' : 'none';
            });
        }
        
        // Search input event listener
        searchInput.addEventListener('input', (e) => {
            filterPublications(e.target.value);
        });
    });
}