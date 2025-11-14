import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { Document, Page, pdfjs } from 'react-pdf';
import { PaperCraft } from 'papercraft';

pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

const SemanticCitationsViewer = () => {
    const [doi, setDoi] = useState(null);
    const [pdfUrl, setPdfUrl] = useState(null);
    const [citations, setCitations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const root = document.getElementById('papercraft-root');
        const doiFromData = root.getAttribute('data-doi');
        setDoi(doiFromData);
    }, []);

    useEffect(() => {
        if (!doi) return;

        const fetchCitations = async () => {
            try {
                const response = await fetch(`/citations/api/get-citation-context/?citing_doi=${doi}`);
                if (!response.ok) {
                    throw new Error('Failed to fetch citation contexts');
                }
                const data = await response.json();
                setPdfUrl(data.trace.pdf_url);
                setCitations(data.contexts);
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchCitations();
    }, [doi]);

    if (loading) {
        return <div>Loading...</div>;
    }

    if (error) {
        return <div className="alert alert-danger">{error}</div>;
    }

    if (!pdfUrl) {
        return <div className="alert alert-warning">No PDF available for this DOI.</div>;
    }

    const overlays = citations.map(citation => ({
        id: `citation-${citation.id}`,
        page: citation.page_number,
        bounds: citation.bounding_boxes,
        type: 'highlight',
        backgroundColor: 'rgba(255, 255, 0, 0.3)',
    }));

    return (
        <PaperCraft pdfUrl={pdfUrl} overlays={overlays}>
            {({ document, pages }) => (
                <div>
                    {document}
                    {pages}
                </div>
            )}
        </PaperCraft>
    );
};

const container = document.getElementById('papercraft-root');
const root = ReactDOM.createRoot(container);
root.render(<SemanticCitationsViewer />);
