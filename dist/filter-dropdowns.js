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
      const details = document.createElement('details');
      details.className = 'filter-dropdown';
      const summary = document.createElement('summary');
      summary.setAttribute('aria-label', title);
      const menu = document.createElement('div');
      menu.className = 'filter-menu';
      menu.setAttribute('role', 'group');
      menu.setAttribute('aria-label', title);
      details.append(summary, menu);
      label.replaceWith(field);
      field.append(caption, select, details);
      select.hidden = true;
      control = {details, summary, menu};
      controls.set(select, control);

      // Open one menu at a time and close it when keyboard focus leaves the field.
      details.addEventListener('toggle', () => {
        if (details.open) document.querySelectorAll('.filter-dropdown[open]').forEach(other => {
          if (other !== details) other.open = false;
        });
      });
      details.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          details.open = false;
          summary.focus();
        }
      });
      details.addEventListener('focusout', event => {
        if (!details.contains(event.relatedTarget)) details.open = false;
      });
    }

    const {details, summary, menu} = control;
    const selected = [...select.options].filter(option => option.selected && option.value);
    const allLabel = [...select.options].find(option => !option.value)?.textContent || 'All values';
    summary.textContent = selected.length === 0 ? allLabel :
      selected.length === 1 ? selected[0].textContent : selected.length + ' selected';
    summary.title = selected.map(option => option.textContent).join(', ');
    summary.setAttribute('aria-disabled', String(select.disabled));
    summary.onclick = event => { if (select.disabled) event.preventDefault(); };
    summary.tabIndex = select.disabled ? -1 : 0;
    if (select.disabled) details.open = false;
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

// Clicking elsewhere dismisses a menu without changing its selections.
document.addEventListener('pointerdown', event => {
  document.querySelectorAll('.filter-dropdown[open]').forEach(menu => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
