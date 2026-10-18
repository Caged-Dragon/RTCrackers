/* Shared customer combo catalogue + secure admin combo manager.
 * All layout state remains client-local; combo mutations go through the
 * authenticated FastAPI admin endpoints, never directly to Supabase from JS.
 */
(() => {
  'use strict';
  const api = window.RTApi;
  if (!api) return;
  const esc = api.escapeHtml || (v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
  const attr = api.escapeAttr || esc;
  const money = api.money || (v => '₹' + Number(v || 0).toLocaleString('en-IN'));
  const pageUrl = api.pageUrl || (p => p || '#');
  const customerApi = api.customerApi;
  const adminApi = api.adminApi;
  const cfg = api.config || {};
  const pathname = location.pathname.toLowerCase();

  const productFallback = cfg.productImage || '';
  const whatsapp = cfg.whatsapp || '918124100501';
  const isHome = /customer_page_1_home_storefront|home_red_thunder_crackers/.test(pathname) || pathname === '/';
  const isCataloguePage = /combo_packs_red_thunder_crackers/.test(pathname) || pathname === '/combos';

  function comboCard(combo) {
    const items = Array.isArray(combo.items) ? combo.items : [];
    const shownPrice = combo.display_price ?? combo.calculated_price ?? combo.manual_price ?? 0;
    const normalPrice = combo.calculated_price ?? combo.live_items_total ?? null;
    const photo = combo.image_url || items[0]?.image_url || productFallback;
    const itemMarkup = items.map(item => `<li class="rtc-combo-item-line"><span>${esc(item.name || item.item_label || 'Product')}</span><strong>× ${Number(item.quantity || 1)}</strong></li>`).join('');
    return `<article class="rtc-combo-card">
      <img class="rtc-combo-photo" loading="lazy" src="${attr(photo)}" alt="${attr(combo.name || 'Combo pack')}" onerror="this.onerror=null;this.src='${attr(productFallback)}'">
      <div class="rtc-combo-card-body">
        <div class="rtc-combo-title-row"><div><span class="rtc-combo-tier">${esc(combo.budget_tier || 'Combo pack')}</span><h3>${esc(combo.short_title || combo.name)}</h3></div>${combo.badge_text ? `<span class="rtc-combo-badge">${esc(combo.badge_text)}</span>` : ''}</div>
        ${combo.tagline ? `<p class="rtc-combo-tagline">${esc(combo.tagline)}</p>` : ''}
        ${combo.description ? `<p class="rtc-combo-desc">${esc(combo.description)}</p>` : ''}
        <div class="rtc-combo-price"><strong>${money(shownPrice)}</strong>${combo.is_offer_active && normalPrice ? `<del>${money(normalPrice)}</del><span>${esc(combo.combo_offer_label || 'Special offer')}</span>` : ''}</div>
        <details class="rtc-combo-details"><summary>${Number(combo.distinct_products || items.length)} product lines · ${Number(combo.total_units || items.reduce((n,x)=>n+Number(x.quantity||1),0))} units</summary><ul>${itemMarkup || '<li>Pack contents are not available yet.</li>'}</ul></details>
        <a class="rtc-combo-enquire" href="https://wa.me/${encodeURIComponent(whatsapp)}?text=${encodeURIComponent('Hello, I am interested in the '+(combo.name||'combo pack')+' ('+(combo.combo_code||'')+'). Please share ordering details.')}" target="_blank" rel="noopener">Enquire about this combo</a>
      </div>
    </article>`;
  }

  async function mountCustomerCombos() {
    if (!isHome && !isCataloguePage) return;
    let host;
    if (isCataloguePage) {
      host = document.getElementById('rtc-combo-catalogue');
      if (!host) {
        const main = document.querySelector('main');
        if (!main) return;
        host = document.createElement('section');
        host.id = 'rtc-combo-catalogue';
        host.className = 'rtc-combo-section';
        main.appendChild(host);
      }
    } else {
      host = document.getElementById('rtc-home-combo-section');
      if (!host) {
        const main = document.querySelector('main');
        if (!main) return;
        host = document.createElement('section');
        host.id = 'rtc-home-combo-section';
        host.className = 'rtc-combo-section';
        main.appendChild(host);
      }
    }
    host.innerHTML = '<p class="rtc-combo-loading">Loading combo packs…</p>';
    try {
      const result = await customerApi('/combos' + (isCataloguePage ? '' : '?homepage_only=true'));
      const items = result?.items || [];
      const heading = isCataloguePage ? 'Festival Combo Packs' : 'Curated Combo Packs';
      host.innerHTML = `<div class="rtc-combo-section-head"><div><span class="rtc-combo-eyebrow">Direct from Sivakasi</span><h2>${heading}</h2><p>${isCataloguePage ? 'Explore pack contents, bundle pricing and current offers.' : 'Ready-made packs for family celebrations and festive occasions.'}</p></div>${isCataloguePage ? `<a href="${attr(pageUrl('shop'))}">Shop individual products →</a>` : `<a href="${attr(pageUrl('combos'))}">View all combos →</a>`}</div>` +
        (items.length ? `<div class="rtc-combo-grid">${items.map(comboCard).join('')}</div>` : '<div class="rtc-combo-empty"><strong>No combo packs are currently published.</strong><p>Please check back soon.</p></div>');
    } catch (error) {
      console.warn('Combo catalogue unavailable', error);
      host.innerHTML = '<div class="rtc-combo-empty"><strong>Combo packs are temporarily unavailable.</strong><p>Please try again later.</p></div>';
    }
  }

  function mountAdminComboManager() {
    const adminPage = /primary_admin_complete_command_center|admin_page_2_product_management/.test(pathname);
    if (!api.isAdmin || !adminPage || !adminApi || document.getElementById('rtc-combo-admin')) return;

    const main = document.querySelector('main');
    if (!main) return;
    const panel = document.createElement('section');
    panel.id = 'rtc-combo-admin';
    panel.className = 'rtc-combo-admin';
    panel.innerHTML = `
      <div class="rtc-combo-admin-head">
        <div><span class="rtc-combo-eyebrow">Catalog operations</span><h2>Combo Pack Manager</h2><p>Manage bundle contents, images, pricing, offer windows and homepage visibility.</p></div>
        <button type="button" id="rtc-combo-create" class="rtc-combo-primary">＋ Create Combo Pack</button>
      </div>
      <div id="rtc-combo-status" class="rtc-combo-status" role="status"></div>
      <div id="rtc-combo-admin-list" class="rtc-combo-admin-list"><p>Loading combo packs…</p></div>
      <dialog id="rtc-combo-dialog" class="rtc-combo-dialog">
        <form id="rtc-combo-form">
          <div class="rtc-combo-dialog-head"><div><h3 id="rtc-combo-dialog-title">Create Combo Pack</h3><p>Choose the products and set the bundle price.</p></div><button type="button" id="rtc-combo-close" class="rtc-combo-x" aria-label="Close form">×</button></div>
          <div class="rtc-combo-form-grid">
            <label>Combo code<input id="rtc-c-code" required maxlength="40" placeholder="RT-COMBO-001"></label>
            <label>Name<input id="rtc-c-name" required maxlength="160" placeholder="Family Celebration Pack"></label>
            <label>Slug<input id="rtc-c-slug" required maxlength="180" pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="family-celebration-pack"></label>
            <label>Short title<input id="rtc-c-short" maxlength="100"></label>
            <label class="rtc-span-two">Tagline<input id="rtc-c-tagline" maxlength="240"></label>
            <label class="rtc-span-two">Description<textarea id="rtc-c-description" rows="3" maxlength="2500"></textarea></label>
            <div class="rtc-combo-image-control rtc-span-two"><img id="rtc-c-image-preview" alt="Combo image preview" src="${attr(productFallback)}"><div><label>Upload combo image<input type="file" id="rtc-c-image-file" accept="image/jpeg,image/png,image/webp,image/avif"></label><small>JPG, PNG, WebP or AVIF · maximum 5 MB. Uploaded to the same shared storage project.</small><label>Image URL<input id="rtc-c-image-url" type="url" placeholder="https://…"></label></div></div>
            <label>Budget tier<select id="rtc-c-tier"><option value="">Not set</option><option>STARTER</option><option>FAMILY</option><option>FESTIVAL</option><option>PREMIUM</option><option>GRAND</option></select></label>
            <label>Pricing mode<select id="rtc-c-pricing-mode"><option value="LIVE_SUM">Live product total</option><option value="MANUAL">Manual bundle price</option></select></label>
            <label>Manual price (₹)<input id="rtc-c-manual" type="number" min="0.01" step="0.01" placeholder="Required for manual price"></label>
            <label>Badge text<input id="rtc-c-badge" maxlength="80" placeholder="BEST VALUE"></label>
            <label>Display order<input id="rtc-c-order" type="number" min="0" step="1" value="0"></label>
            <label>Offer price (₹)<input id="rtc-c-offer" type="number" min="0.01" step="0.01"></label>
            <label>Offer label<input id="rtc-c-offer-label" maxlength="100" placeholder="Festival Offer"></label>
            <label>Offer starts<input id="rtc-c-offer-start" type="datetime-local"></label>
            <label>Offer ends<input id="rtc-c-offer-end" type="datetime-local"></label>
            <div class="rtc-combo-checks rtc-span-two"><label><input type="checkbox" id="rtc-c-active" checked> Active</label><label><input type="checkbox" id="rtc-c-featured"> Featured</label><label><input type="checkbox" id="rtc-c-homepage"> Show on homepage</label></div>
            <div class="rtc-span-two"><div class="rtc-combo-items-head"><div><h4>Products in this pack</h4><p>Select active products and quantities.</p></div><button type="button" id="rtc-c-add-item" class="rtc-combo-secondary">＋ Add product</button></div><div id="rtc-c-items" class="rtc-combo-item-rows"></div></div>
            <div id="rtc-c-form-status" class="rtc-span-two" role="status"></div>
          </div>
          <div class="rtc-combo-dialog-footer"><button type="button" id="rtc-cancel" class="rtc-combo-secondary">Cancel</button><button type="submit" id="rtc-c-save" class="rtc-combo-primary">Save combo pack</button></div>
        </form>
      </dialog>`;
    const content = main.querySelector(':scope > div') || main;
    content.prepend(panel);

    const nav = document.querySelector('nav');
    if (nav && !nav.querySelector('[data-rtc-combo-nav]')) {
      const link = document.createElement('a');
      link.href = '#rtc-combo-admin';
      link.dataset.rtcComboNav = '1';
      link.className = 'flex items-center px-space-sm py-2 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors font-label-md text-label-md';
      link.innerHTML = '<span class="material-symbols-outlined mr-space-sm text-[18px]">inventory</span>Combo Packs';
      link.onclick = event => { event.preventDefault(); panel.scrollIntoView({behavior:'smooth',block:'start'}); };
      nav.appendChild(link);
    }

    const byId = id => document.getElementById(id);
    const list = byId('rtc-combo-admin-list');
    const status = byId('rtc-combo-status');
    const dialog = byId('rtc-combo-dialog');
    const form = byId('rtc-combo-form');
    let packs = [], products = [], editingId = null;

    const message = (text, error=false) => {
      const node = byId('rtc-c-form-status');
      if (node) { node.textContent = text || ''; node.className = 'rtc-span-two ' + (error ? 'rtc-combo-error' : 'rtc-combo-success'); }
    };
    const iso = id => byId(id).value ? new Date(byId(id).value).toISOString() : null;
    const localDate = value => {
      if (!value) return '';
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return '';
      const pad=n=>String(n).padStart(2,'0');
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };
    function addItemRow(item={}) {
      const row = document.createElement('div');
      row.className = 'rtc-combo-item-row';
      row.innerHTML = `<label>Product<select class="rtc-c-item-product"><option value="">Select a product…</option>${products.map(p=>`<option value="${attr(p.id)}" ${String(p.id)===String(item.product_id || item.products?.id)?'selected':''}>${esc(p.name)} · #${esc(p.product_code)} · ${money(p.factory_rate)}</option>`).join('')}</select></label><label>Quantity<input class="rtc-c-item-qty" type="number" min="1" max="10000" step="1" value="${Number(item.quantity||1)}"></label><button type="button" class="rtc-combo-secondary rtc-c-remove-item">Remove</button><label class="rtc-span-two">Item label<input class="rtc-c-item-label" maxlength="120" value="${attr(item.item_label||'')}"></label><label class="rtc-span-two">Item note<input class="rtc-c-item-note" maxlength="500" value="${attr(item.item_note||'')}"></label>`;
      row.querySelector('.rtc-c-remove-item').onclick = () => row.remove();
      byId('rtc-c-items').appendChild(row);
    }
    function resetForm() {
      editingId = null;
      form.reset();
      byId('rtc-combo-dialog-title').textContent = 'Create Combo Pack';
      byId('rtc-c-save').textContent = 'Save combo pack';
      byId('rtc-c-order').value = '0';
      byId('rtc-c-active').checked = true;
      byId('rtc-c-image-preview').src = productFallback;
      byId('rtc-c-items').innerHTML = '';
      message('');
      addItemRow();
    }
    function openCreate() { resetForm(); dialog.showModal(); }
    function openEdit(pack) {
      resetForm();
      editingId = String(pack.id);
      byId('rtc-combo-dialog-title').textContent = 'Edit Combo Pack';
      byId('rtc-c-save').textContent = 'Save changes';
      const pairs = [
        ['rtc-c-code',pack.combo_code],['rtc-c-name',pack.name],['rtc-c-slug',pack.slug],['rtc-c-short',pack.short_title],
        ['rtc-c-tagline',pack.tagline],['rtc-c-description',pack.description],['rtc-c-image-url',pack.image_url],
        ['rtc-c-tier',pack.budget_tier],['rtc-c-pricing-mode',pack.pricing_mode],['rtc-c-manual',pack.manual_price],
        ['rtc-c-badge',pack.badge_text],['rtc-c-order',pack.display_order],['rtc-c-offer',pack.combo_offer_price],
        ['rtc-c-offer-label',pack.combo_offer_label],['rtc-c-offer-start',localDate(pack.combo_offer_starts_at)],
        ['rtc-c-offer-end',localDate(pack.combo_offer_ends_at)]
      ];
      pairs.forEach(([id,value])=>byId(id).value=value??'');
      byId('rtc-c-active').checked=!!pack.is_active;
      byId('rtc-c-featured').checked=!!pack.is_featured;
      byId('rtc-c-homepage').checked=!!pack.show_on_homepage;
      if(pack.image_url)byId('rtc-c-image-preview').src=pack.image_url;
      byId('rtc-c-items').innerHTML='';
      const items=pack.combo_pack_items||pack.items||[];
      (items.length?items:[{}]).forEach(addItemRow);
      dialog.showModal();
    }
    function renderList() {
      if (!packs.length) { list.innerHTML='<div class="rtc-combo-empty"><strong>No combo packs were returned by the database.</strong></div>'; return; }
      list.innerHTML = packs.map(p=>{
        const items=p.combo_pack_items||p.items||[];
        const names=items.map(i=>i.products?.name||i.name||i.item_label||'Product').slice(0,4).map(esc).join(', ');
        return `<article class="rtc-combo-admin-card"><img src="${attr(p.image_url||productFallback)}" alt="" onerror="this.onerror=null;this.src='${attr(productFallback)}'"><div class="rtc-combo-admin-info"><div class="rtc-combo-admin-meta"><span class="${p.is_active?'rtc-combo-active':'rtc-combo-inactive'}">${p.is_active?'ACTIVE':'INACTIVE'}</span><span>${esc(p.combo_code)}</span>${p.show_on_homepage?'<span>HOME</span>':''}</div><h3>${esc(p.name)}</h3><p>${items.length} product lines · ${esc(p.pricing_mode)}</p><p class="rtc-combo-muted">${names}</p><div class="rtc-combo-actions"><button class="rtc-combo-primary" data-edit-combo="${attr(p.id)}">Edit</button>${p.is_active?'<button class="rtc-combo-secondary" data-deactivate-combo="'+attr(p.id)+'">Deactivate</button>':''}</div></div></article>`;
      }).join('');
      list.querySelectorAll('[data-edit-combo]').forEach(b=>b.onclick=()=>{const p=packs.find(x=>String(x.id)===b.dataset.editCombo);if(p)openEdit(p);});
      list.querySelectorAll('[data-deactivate-combo]').forEach(b=>b.onclick=async()=>{if(!confirm('Deactivate this combo pack? It remains in the database.'))return;try{await adminApi('/combos/'+encodeURIComponent(b.dataset.deactivateCombo),{method:'DELETE'});status.textContent='Combo pack deactivated.';await reload();}catch(e){status.textContent=e.message;status.className='rtc-combo-status rtc-combo-error';}});
    }
    async function reload() {
      status.textContent='Loading from database…';
      try {
        const [p,c]=await Promise.all([adminApi('/combos'),adminApi('/combos/products')]);
        packs=Array.isArray(p?.items)?p.items:[];
        products=Array.isArray(c?.items)?c.items:[];
        status.textContent=`${packs.length} combo packs · ${products.length} active products available`;
        renderList();
      } catch (error) {
        list.innerHTML=`<div class="rtc-combo-empty rtc-combo-error">Could not load the combo catalogue: ${esc(error.message)}. Check your admin access and server-side Supabase configuration.</div>`;
        status.textContent='Database connection required';
        status.className='rtc-combo-status rtc-combo-error';
      }
    }

    byId('rtc-combo-create').onclick=openCreate;
    byId('rtc-combo-close').onclick=()=>dialog.close();
    byId('rtc-cancel').onclick=()=>dialog.close();
    byId('rtc-c-add-item').onclick=()=>addItemRow();
    byId('rtc-c-pricing-mode').onchange=()=>{byId('rtc-c-manual').required=byId('rtc-c-pricing-mode').value==='MANUAL';};
    byId('rtc-c-name').oninput=()=>{
      if(editingId)return;
      byId('rtc-c-slug').value=byId('rtc-c-name').value.toLowerCase().trim().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
      if(!byId('rtc-c-code').value)byId('rtc-c-code').value='RT-'+byId('rtc-c-slug').value.toUpperCase().slice(0,34);
    };
    byId('rtc-c-image-url').oninput=()=>{byId('rtc-c-image-preview').src=byId('rtc-c-image-url').value||productFallback;};
    byId('rtc-c-image-file').onchange=async()=>{
      const file=byId('rtc-c-image-file').files?.[0];if(!file)return;
      const data=new FormData();data.append('file',file);message('Uploading image…');
      try{const result=await adminApi('/combos/image',{method:'POST',body:data});byId('rtc-c-image-url').value=result.url;byId('rtc-c-image-preview').src=result.url;message('Image uploaded; save the combo pack to apply it.');}
      catch(error){message(error.message||'Image upload failed.',true);}
      finally{byId('rtc-c-image-file').value='';}
    };
    form.onsubmit=async event=>{
      event.preventDefault();
      const rows=[...byId('rtc-c-items').querySelectorAll('.rtc-combo-item-row')];
      const items=rows.map((row,index)=>({product_id:row.querySelector('.rtc-c-item-product').value,quantity:Number(row.querySelector('.rtc-c-item-qty').value||1),display_order:index,item_label:row.querySelector('.rtc-c-item-label').value.trim()||null,item_note:row.querySelector('.rtc-c-item-note').value.trim()||null}));
      if(!items.length||items.some(i=>!i.product_id)){message('Choose an active product in every row.',true);return;}
      const body={combo_code:byId('rtc-c-code').value.trim(),name:byId('rtc-c-name').value.trim(),slug:byId('rtc-c-slug').value.trim(),short_title:byId('rtc-c-short').value.trim()||null,description:byId('rtc-c-description').value.trim()||null,tagline:byId('rtc-c-tagline').value.trim()||null,image_url:byId('rtc-c-image-url').value.trim()||null,budget_tier:byId('rtc-c-tier').value||null,pricing_mode:byId('rtc-c-pricing-mode').value,manual_price:byId('rtc-c-manual').value?Number(byId('rtc-c-manual').value):null,badge_text:byId('rtc-c-badge').value.trim()||null,is_active:byId('rtc-c-active').checked,is_featured:byId('rtc-c-featured').checked,show_on_homepage:byId('rtc-c-homepage').checked,display_order:Number(byId('rtc-c-order').value||0),combo_offer_price:byId('rtc-c-offer').value?Number(byId('rtc-c-offer').value):null,combo_offer_label:byId('rtc-c-offer-label').value.trim()||null,combo_offer_starts_at:iso('rtc-c-offer-start'),combo_offer_ends_at:iso('rtc-c-offer-end'),items};
      const save=byId('rtc-c-save');save.disabled=true;save.textContent='Saving…';
      try{await adminApi('/combos'+(editingId?'/'+encodeURIComponent(editingId):''),{method:editingId?'PUT':'POST',body:JSON.stringify(body)});dialog.close();await reload();status.textContent='Combo pack saved to the database.';}
      catch(error){message(error.message||'Could not save combo pack.',true);}
      finally{save.disabled=false;save.textContent=editingId?'Save changes':'Save combo pack';}
    };
    reload();
  }

  function boot() {
    if (isHome || isCataloguePage) mountCustomerCombos();
    mountAdminComboManager();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
