# face_forget
Deletes a person from the face recognition database (faces/faces.json embeddings + faces/<Name>.jpg thumbnail, sent to Recycle Bin). Matches the name loosely so speech-to-text spelling doesn't matter. Leaves their vault People/<Name>.md note alone — only clears recognition data, not memories.
**Say:** "clear the name Emma from this database" / "forget Luke's face" / "delete Jacob from the face database"
**Args:** `name`.
