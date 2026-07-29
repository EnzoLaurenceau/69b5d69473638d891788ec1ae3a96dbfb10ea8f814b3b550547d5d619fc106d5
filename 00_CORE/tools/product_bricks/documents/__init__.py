"""tools.product_bricks.documents — MANIPULATION DE FICHIERS/PDF dans un produit.

Expose :
  - stirling_pdf: PDF self-host merge/split/OCR/sign/convert/compress.
                  Jamais coder la manip PDF à la main — on appelle ça.
                  deploy: docker run frooodle/s-pdf
"""

from . import stirling_pdf
