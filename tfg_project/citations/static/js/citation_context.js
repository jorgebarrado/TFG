document.addEventListener('DOMContentLoaded', () => {
    const contextModal = new bootstrap.Modal(document.getElementById('contextModal'));
    const contextResults = document.getElementById('context-results');
    const contextFallback = document.getElementById('context-fallback');
    const contextLoading = document.getElementById('context-loading');
    const createReportBtn = document.getElementById('create-report-btn');

    document.querySelectorAll('button[data-doi]').forEach(button => {
        button.addEventListener('click', () => {
            const doi = button.dataset.doi;
            contextLoading.classList.remove('d-none');
            contextResults.classList.add('d-none');
            contextFallback.classList.add('d-none');
            createReportBtn.disabled = true;

            fetch(`/citations/api/get-citation-context/?doi=${doi}`)
                .then(response => response.json())
                .then(data => {
                    contextLoading.classList.add('d-none');
                    if (data.contexts && data.contexts.length > 0) {
                        contextResults.innerHTML = data.contexts.map(context => `<p>${context}</p>`).join('');
                        contextResults.classList.remove('d-none');
                        createReportBtn.disabled = false;
                    } else {
                        contextFallback.classList.remove('d-none');
                    }
                })
                .catch(() => {
                    contextLoading.classList.add('d-none');
                    contextFallback.classList.remove('d-none');
                });

            contextModal.show();
        });
    });

    document.getElementById('extract-from-url').addEventListener('click', () => {
        const pdfUrl = document.getElementById('pdf-url').value;
        if (!pdfUrl) {
            alert('Please enter a valid PDF URL.');
            return;
        }
        // This functionality is not implemented yet.
        alert('Extracting from URL is not yet implemented.');
    });
});
