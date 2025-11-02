// EN/ES: Minimal JS to upload manuscript and render JSON results.
console.log("citation_extractor.js LOADED");
window.uploadAndExtract = uploadAndExtract;
async function uploadAndExtract(urlName) {
  const fileInput = document.getElementById("manuscript");
  const results = document.getElementById("results");
  results.textContent = "Processing...";
  const fd = new FormData();
  if (!fileInput.files[0]) {
    results.textContent = "Please choose a file / Por favor selecciona un archivo";
    return;
  }
  fd.append("manuscript", fileInput.files[0]);
  const res = await fetch(urlName, { method: "POST", body: fd });
  const data = await res.json();
  results.textContent = JSON.stringify(data, null, 2);
}
