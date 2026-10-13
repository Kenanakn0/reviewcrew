export async function loadWidgets(widgetIds) {
  const widgets = [];
  for (const id of widgetIds) {
    const response = await fetch(`/api/widgets/${id}`);
    widgets.push(await response.json());
  }
  return widgets;
}
