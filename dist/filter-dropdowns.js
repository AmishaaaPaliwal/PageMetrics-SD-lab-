// Preserve native select values so the existing FormData filtering and permissions still apply.
const controls = new WeakMap();

export function refreshDropdowns(form) {
  form.querySelectorAll('select[multiple]').forEach(select => {
    let control = controls.get(select);
    if (!control) {
      const label = select.parentElement;
      const title = label.firstChild.textContent.trim();
      const field = document.createElement('div');
      field.className = 'dropdown-field';
      const caption = document.createElement('span');
      caption.className = 'dropdown-caption';
      caption.textContent = title;
      const details = document.createElement('div');
      details.className = 'filter-dropdown';
      const summary = document.createElement('button');
      summary.type = 'button';
      summary.className = 'filter-trigger';
      summary.setAttribute('aria-label', title);
      summary.setAttribute('aria-expanded', 'false');
      const menu = document.createElement('div');
      menu.className = 'filter-menu';
      menu.hidden = true;
      menu.setAttribute('role', 'group');
      menu.setAttribute('aria-label', title);
      details.append(summary, menu);
      label.replaceWith(field);
      field.append(caption, select, details);
      select.hidden = true;
      control = {details, summary, menu};
      controls.set(select, control);

      // Toggle panels explicitly, without native details toggle events or focusout mutations.
      summary.onclick = () => {
        if (select.disabled) return;
        const shouldOpen = menu.hidden;
        closeDropdowns();
        menu.hidden = !shouldOpen;
        summary.setAttribute('aria-expanded', String(shouldOpen));
      };
      details.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          closeDropdowns();
          summary.focus();
        }
      });

    }

    const {details, summary, menu} = control;
    const selected = [...select.options].filter(option => option.selected && option.value);
    const allLabel = [...select.options].find(option => !option.value)?.textContent || 'All values';
    summary.textContent = selected.length === 0 ? allLabel :
      selected.length === 1 ? selected[0].textContent : selected.length + ' selected';
    summary.title = selected.map(option => option.textContent).join(', ');
    summary.setAttribute('aria-disabled', String(select.disabled));
    summary.disabled = select.disabled;
    summary.tabIndex = select.disabled ? -1 : 0;
    menu.hidden = true;
    summary.setAttribute('aria-expanded', 'false');
    menu.replaceChildren();

    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'filter-all';
    all.textContent = allLabel + ' · Clear selection';
    all.onclick = () => {
      [...select.options].forEach(option => { option.selected = false; });
      select.dispatchEvent(new Event('change', {bubbles: true}));
      refreshDropdowns(form);
      summary.focus();
    };
    menu.append(all);
    [...select.options].filter(option => option.value).forEach(option => {
      const row = document.createElement('label');
      row.className = 'filter-choice';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = option.selected;
      checkbox.disabled = select.disabled || option.disabled;
      const text = document.createElement('span');
      text.textContent = option.textContent;
      checkbox.onchange = () => {
        option.selected = checkbox.checked;
        [...select.options].filter(item => !item.value).forEach(item => { item.selected = false; });
        const values = [...select.selectedOptions].filter(item => item.value);
        summary.textContent = values.length === 0 ? allLabel :
          values.length === 1 ? values[0].textContent : values.length + ' selected';
        summary.title = values.map(item => item.textContent).join(', ');
        select.dispatchEvent(new Event('change', {bubbles: true}));
      };
      row.append(checkbox, text);
      menu.append(row);
    });
  });
}

// Close menus without rebuilding their focused checkbox elements.
function closeDropdowns() {
  document.querySelectorAll('.filter-dropdown').forEach(dropdown => {
    dropdown.querySelector('.filter-menu').hidden = true;
    dropdown.querySelector('.filter-trigger').setAttribute('aria-expanded', 'false');
  });
}

document.addEventListener('pointerdown', event => {
  if (!event.target.closest('.filter-dropdown')) closeDropdowns();
});
document.addEventListener('focusin', event => {
  if (!event.target.closest('.filter-dropdown')) closeDropdowns();
});
