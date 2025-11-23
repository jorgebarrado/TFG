import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';

const SemanticCitationsViewer = () => {
    const [doi, setDoi] = useState(null);
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
                const response = await fetch(`/citations/api/get-semantic-citations/?doi=${doi}`);
                if (!response.ok) {
                    throw new Error('Failed to fetch citations');
                }
                const data = await response.json();
                setCitations(data.citations);
            } catch (err) G
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

    return (
        <ul className="list-group">
            {citations.map(citation => (
                <li key={citation.doi} className="list-group-item">
                    <h5>{citation.title}</h5>
                    <p>{citation.authors}</p>
                    <p>
                        <a href={`https://doi.org/${citation.doi}`} target="_blank" rel="noopener noreferrer">
                            {citation.doi}
                        </a>
                    </p>
                </li>
            ))}
        </ul>
    );
};

const container = document.getElementById('papercraft-root');
const root = ReactDOM.createRoot(container);
root.render(<SemanticCitationsViewer />);
