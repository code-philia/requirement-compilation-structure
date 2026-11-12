// Compiler-owned Arco accessibility mechanics; no business labels or fixture values.
import type { ReactNode } from 'react';
import type { SelectProps } from '@arco-design/web-react';

/** Name the Select's combobox once, rather than labeling both outer and inner controls. */
export function selectAriaLabel(label: string): SelectProps {
  // Arco 2.66.18 forwards this DOM aria attribute but omits it from SelectProps.
  return { 'aria-label': label } as unknown as SelectProps;
}

/** A visible required marker must not change the source field's accessible name. */
export function requiredLabel(text: string): ReactNode {
  return <span><span aria-hidden="true" style={{ color: '#f53f3f', marginRight: 2 }}>*</span>{text}</span>;
}
