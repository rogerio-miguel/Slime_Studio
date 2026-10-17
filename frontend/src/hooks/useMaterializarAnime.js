import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { criarAnimeDoFeed } from '../api/recursos.js';
import { chaveDoItemDoFeed } from '../inicio/fileiras.js';

// Item de feed/busca do provedor (AniList) → anime no catálogo local e
// navegação pra `/anime/:id`. `POST /api/admin/animes` é get-or-create por slug
// no servidor, então reenvio acidental não duplica. Só uma materialização por
// vez: `chaveEmMaterializacao` (ver `chaveDoItemDoFeed`) serve pra desabilitar o
// card em voo. `definirErro` existe pra página que faz outras escritas no
// catálogo (ex. bookmark de estreia na Home) reportar no mesmo slot de erro.
export function useMaterializarAnime() {
  const navigate = useNavigate();
  const [chaveEmMaterializacao, setChaveEmMaterializacao] = useState(null);
  const [erro, definirErro] = useState(null);

  const materializarEIrPara = useCallback(
    async (item) => {
      if (chaveEmMaterializacao != null) return;
      setChaveEmMaterializacao(chaveDoItemDoFeed(item));
      definirErro(null);
      try {
        const criado = await criarAnimeDoFeed(item);
        navigate(`/anime/${criado.id}`);
      } catch (erroCapturado) {
        console.error('falha ao adicionar anime ao catálogo', erroCapturado);
        definirErro('Não foi possível adicionar este anime ao catálogo — tente novamente.');
      } finally {
        setChaveEmMaterializacao(null);
      }
    },
    [chaveEmMaterializacao, navigate],
  );

  return { materializarEIrPara, chaveEmMaterializacao, erro, definirErro };
}
