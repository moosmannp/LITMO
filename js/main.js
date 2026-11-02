// Start: laedt zuletzt, wenn alle Funktionen der anderen Dateien definiert sind

['domainDesc', 'dataSources', 'extraReqs'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', saveProject);
});

syncThemeToggle();
// erst wissen, ob der Server einen Schluessel hat (DECISIONS 139), dann Modelle und Projekt
(async () => {
  await loadServerConfig();
  updateModelOptions();   // auch fuer ein neues Projekt die Modelle des angezeigten Anbieters
  init();
})();
