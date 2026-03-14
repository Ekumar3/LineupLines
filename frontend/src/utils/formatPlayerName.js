export function formatPlayerName(name) {
  if (!name) return '';
  const parts = name.split(' ');
  if (parts.length === 1) return name;
  return `${parts[0][0]}. ${parts.slice(1).join(' ')}`;
}
