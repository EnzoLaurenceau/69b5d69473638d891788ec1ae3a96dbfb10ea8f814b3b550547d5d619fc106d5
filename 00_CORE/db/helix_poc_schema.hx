// helix_poc_schema.hx — SKETCH POC (à confirmer contre docs.helix-db.com).
// Nœud mémoire de la Forge : texte compressé turbovec + embedding + métadonnées.
// Index vectoriel sur `vector` pour vectorSearchNodes ; index texte sur `text`.
//
// La syntaxe HelixQL exacte (types, déclaration d'index, AddV) dépend de ta
// version d'Helix — vérifier docs: /database/querying-guide/search avant `helix deploy`.

N::ForgeDoc {
    text: String,
    agent: String,
    score: F64,
    vector: [F64]        // embedding turbovec (compress-before)
}

// Requête d'insertion (forme indicative) :
// QUERY addForgeDoc(text: String, agent: String, score: F64, vector: [F64]) =>
//     doc <- AddV<ForgeDoc>({ text: text, agent: agent, score: score, vector: vector })
//     RETURN doc

// Requête de recherche vectorielle (forme indicative) :
// QUERY searchForgeDocs(query: [F64], k: I64) =>
//     hits <- SearchV<ForgeDoc>(query, k)
//     RETURN hits
