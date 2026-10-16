// Computed cells for the shared team budget sheet. Any member can edit a cell's formula.

export function evaluateCell(cell, values) {
  if (!cell.formula) {
    return cell.value;
  }
  // Formulas look like "=A1 + B2 * 0.2"; references are replaced by their values.
  const expression = cell.formula
    .slice(1)
    .replace(/[A-Z]+[0-9]+/g, (ref) => String(values[ref] ?? 0));
  return eval(expression);
}
