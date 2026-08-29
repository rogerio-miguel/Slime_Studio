"""Sub-pacote de busca em fontes de streaming (`extractors/busca/`).

Três módulos, importados sempre direto do submódulo (sem re-export aqui):

- `termos`: geração dos termos de busca a partir de um título.
- `correspondencia`: correspondência entre o título buscado e o card devolvido.
- `servico`: serviço de busca com a escada de variantes, sobre resiliência /
  circuit breaker.
"""
