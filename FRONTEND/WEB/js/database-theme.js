/* Public database-backed theme for the main portfolio/store pages.
 * Reads only RLS-protected main/home settings with a publishable key.
 * It never stores or writes browser dimensions, zoom, or section sizing.
 */
(() => {
  'use strict';
  const SUPABASE_URL = 'https://ypmiinmkyvzdpakbkers.supabase.co';
  const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_5qcy4L4sPBxHqRdvk_A1kw_tPJPXxhm';
  const root = document.documentElement;

  const cssVars = {
    background_color: '--rtc-db-background',
    surface_color: '--rtc-db-surface',
    surface_elevated_color: '--rtc-db-surface-elevated',
    section_color: '--rtc-db-section',
    header_color: '--rtc-db-header',
    footer_color: '--rtc-db-footer',
    text_color: '--rtc-db-text',
    muted_text_color: '--rtc-db-muted',
    heading_color: '--rtc-db-heading',
    primary_color: '--rtc-db-primary',
    primary_dark_color: '--rtc-db-primary-dark',
    secondary_color: '--rtc-db-secondary',
    accent_color: '--rtc-db-accent',
    link_color: '--rtc-db-link',
    button_background_color: '--rtc-db-button-background',
    button_text_color: '--rtc-db-button-text',
    border_color: '--rtc-db-border',
    border_strong_color: '--rtc-db-border-strong',
    input_background_color: '--rtc-db-input-background',
    input_border_color: '--rtc-db-input-border',
    card_shadow_color: '--rtc-db-card-shadow',
    hero_background_color: '--rtc-db-hero-background',
    banner_background_color: '--rtc-db-banner-background',
    nav_background_color: '--rtc-db-nav-background',
    nav_text_color: '--rtc-db-nav-text',
    font_heading: '--rtc-db-font-heading',
    font_body: '--rtc-db-font-body',
    radius_small: '--rtc-db-radius-small',
    radius_medium: '--rtc-db-radius-medium',
    radius_large: '--rtc-db-radius-large'
  };
  const cssField = {
    font_family: 'font-family', font_size: 'font-size', font_weight: 'font-weight',
    line_height: 'line-height', letter_spacing: 'letter-spacing', text_color: 'color',
    background_color: 'background-color', border_color: 'border-color',
    border_width: 'border-width', border_radius: 'border-radius', box_shadow: 'box-shadow',
    padding: 'padding', margin: 'margin', width: 'width', max_width: 'max-width',
    text_align: 'text-align'
  };
  const componentSelectors = {
    top_banner: '#homeBanners',
    header: 'header.site-header',
    nav: '.site-header .main-nav',
    hero: 'main > .hero',
    hero_eyebrow: '.hero .hero-eyebrow',
    hero_heading: '.hero h1',
    hero_tagline: '.hero .hero-tagline',
    hero_description: '.hero .lead',
    hero_buttons: '.hero .hero-cta',
    hero_stats: '.hero .hero-stats',
    about: 'main > .section.section-alt:first-of-type',
    about_heading: 'main > .section.section-alt:first-of-type h2',
    about_paragraph: 'main > .section.section-alt:first-of-type p',
    about_highlights: '.why-choose-us,.why-grid',
    catalogue: '#featuredGrid',
    catalogue_heading: '#featuredGrid',
    product_catalogue: '#featuredGrid',
    shipping: 'main > section.section-alt:last-of-type',
    safety: '.section-safety,.safety-section',
    contact: '.contact-section',
    footer: 'footer.site-footer'
  };

  function safeCssValue(value) {
    if (typeof value !== 'string' && typeof value !== 'number') return null;
    const v = String(value).trim();
    if (!v || v.length > 160 || /[{};]/.test(v) || /url\s*\(|expression\s*\(/i.test(v)) return null;
    return v;
  }

  function applyPage(page) {
    Object.entries(cssVars).forEach(([field, name]) => {
      const value = safeCssValue(page[field]);
      if (value) root.style.setProperty(name, value);
    });
    root.classList.add('rt-db-theme');
  }

  function applyComponent(component) {
    const key = String(component.component_key || '');
    if (!/^[a-z0-9_-]{1,100}$/i.test(key)) return;
    const selectors = [
      '[data-theme-component="' + key + '"]',
      '[data-component-key="' + key + '"]'
    ];
    if (componentSelectors[key]) selectors.push(componentSelectors[key]);
    const unique = [...new Set(selectors)];
    for (const selector of unique) {
      let matches = [];
      try { matches = [...document.querySelectorAll(selector)]; } catch (_) {}
      for (const element of matches) {
        if (component.content_value !== null && component.content_value !== undefined && component.content_value !== '') {
          // Store-managed copy is text-only; it cannot inject arbitrary HTML/scripts.
          element.textContent = String(component.content_value);
        }
        for (const [field, cssProperty] of Object.entries(cssField)) {
          const value = safeCssValue(component[field]);
          if (value) element.style.setProperty(cssProperty, value);
        }
        const tokens = component.component_tokens;
        if (tokens && typeof tokens === 'object' && !Array.isArray(tokens)) {
          for (const [field, cssProperty] of Object.entries(cssField)) {
            const value = safeCssValue(tokens[field]);
            if (value) element.style.setProperty(cssProperty, value);
          }
        }
      }
    }
  }

  async function loadTheme() {
    const headers = {
      apikey: SUPABASE_PUBLISHABLE_KEY,
      Authorization: 'Bearer ' + SUPABASE_PUBLISHABLE_KEY,
      Accept: 'application/json'
    };
    const query = new URLSearchParams({
      select: '*',
      website_key: 'eq.main',
      page_key: 'eq.home',
      is_active: 'eq.true',
      limit: '1'
    });
    const pageResponse = await fetch(SUPABASE_URL + '/rest/v1/theme_page_settings?' + query, {headers, credentials:'omit'});
    if (!pageResponse.ok) throw new Error('Theme page lookup failed');
    const pages = await pageResponse.json();
    if (!Array.isArray(pages) || !pages.length) return;
    applyPage(pages[0]);

    const componentsQuery = new URLSearchParams({
      select: '*',
      website_key: 'eq.main',
      page_key: 'eq.home',
      is_active: 'eq.true',
      order: 'sort_order.asc,theme_component_id.asc',
      limit: '100'
    });
    const componentsResponse = await fetch(SUPABASE_URL + '/rest/v1/theme_component_settings?' + componentsQuery, {headers, credentials:'omit'});
    if (!componentsResponse.ok) throw new Error('Theme component lookup failed');
    const components = await componentsResponse.json();
    if (Array.isArray(components)) components.forEach(applyComponent);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => loadTheme().catch(error => console.warn('Database theme is not available:', error)), {once:true});
  } else {
    loadTheme().catch(error => console.warn('Database theme is not available:', error));
  }
})();
