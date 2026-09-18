# Checklist do teste de campo do OpenDongle

Gerado por `ferramentas/teste_campo.py roteiro --markdown`. Explicação em [TESTE_DE_CAMPO.md](TESTE_DE_CAMPO.md). O ideal é seguir pelo script (`roteiro`), que marca cada passo no log do dongle.

Modo: **USB** = dongle ligado no PC · **tomada** = carregador, sem PC · **qualquer** = tanto faz.

## Base

- [ ] **1. Abrir o painel pelo USB** (`base-painel`, USB)
  - Fazer: Com o dongle no PC, abra http://opendongle.local (ou 192.168.100.1).
  - Esperado: A página inicial abre com o estado da internet; se o painel dormia, aparece “Carregando painel” e em seguida a página.

- [ ] **2. Entrar e sair do painel** (`base-login`, USB)
  - Fazer: Entre em Geral › Conta e senha: vai pedir login. Teste uma senha errada e depois a certa. Use “Sair do painel” e entre de novo.
  - Esperado: Senha errada mostra erro; a certa entra; depois de sair, as páginas protegidas pedem login outra vez.

- [ ] **3. Tema claro, escuro e automático** (`base-tema`, USB)
  - Fazer: Em Geral › Aparência do painel, alterne Claro, Escuro e Automático e navegue por outras páginas.
  - Esperado: O tema muda na hora e continua igual nas outras páginas e depois de recarregar.

- [ ] **4. Busca da página inicial** (`base-busca`, USB)
  - Fazer: Na inicial, busque “senha do wifi”, “bluetooth”, “esqueci a senha” e uma palavra sem sentido.
  - Esperado: Resultados relevantes (os com ❓ abrem a resposta na Ajuda); a palavra sem sentido mostra “Nada encontrado”.

- [ ] **5. Liberar opções avançadas (7 toques)** (`base-avancadas`, USB)
  - Fazer: Em Geral › Sobre, toque 7 vezes em “OpenDongle”.
  - Esperado: A partir do 4º toque aparece a contagem; no 7º abre Opções avançadas, que passam a aparecer na barra antes da Ajuda.

- [ ] **6. Ajuda e FAQ** (`base-ajuda`, qualquer)
  - Fazer: Abra Ajuda, abra e feche algumas perguntas, use a busca da Ajuda e siga um link de dentro de uma resposta.
  - Esperado: Perguntas abrem/fecham; a busca filtra sem se importar com acentos; os links levam à página certa.

- [ ] **7. Painel dorme e acorda** (`base-dormir`, qualquer)
  - Fazer: Feche o painel, espere 6 minutos sem usar e abra de novo.
  - Esperado: Aparece “Carregando painel” por alguns segundos e depois a página, sem erro.

## Geral

- [ ] **8. Status e saúde** (`geral-status`, qualquer)
  - Fazer: Abra Geral › Status e saúde e o “Ver tudo”.
  - Esperado: CPU, RAM, disco e temperatura com valores plausíveis; hardware (Bluetooth, modem, áudio) com estado.

- [ ] **9. Desempenho ao vivo** (`geral-desempenho`, qualquer)
  - Fazer: Abra Geral › Desempenho e deixe aberto 1 minuto.
  - Esperado: Os números se atualizam sozinhos; a lista de processos aparece; processos essenciais não têm “Encerrar”.

- [ ] **10. Data, hora e fuso** (`geral-hora`, qualquer)
  - Fazer: Em Geral › Data e hora, troque o fuso, confira a hora, volte ao fuso certo. Desligue a hora automática, ajuste à mão e religue.
  - Esperado: A hora mostrada acompanha o fuso; o ajuste manual vale; com internet, religar a automática corrige a hora.

- [ ] **11. Espaço em disco** (`geral-espaco`, qualquer)
  - Fazer: Em Geral › Espaço em disco, toque em Analisar agora, espere o resultado e depois em Liberar espaço.
  - Esperado: A análise termina e lista o que ocupa; liberar informa quantos MB saíram.

- [ ] **12. Hardware** (`geral-hardware`, qualquer)
  - Fazer: Abra Geral › Hardware.
  - Esperado: Placa, eMMC, rádios, modem e MACs preenchidos (sem “None” nem erro).

- [ ] **13. Procurar atualizações** (`geral-atualizacoes`, qualquer)
  - Fazer: Com internet, em Geral › Atualizações toque em Procurar atualizações e acompanhe até o fim (não precisa instalar).
  - Esperado: A busca roda em segundo plano e termina com a lista ou “nada a atualizar”, sem travar o painel.

- [ ] **14. Trocar senha (janela em 2 etapas)** (`geral-senha`, qualquer)
  - Fazer: Em Geral › Conta e senha › Trocar senha: teste senha atual errada; depois a certa; na etapa 2 teste senhas diferentes; por fim troque de verdade SEM marcar “Encerrar outras sessões”. Teste o SSH com a senha nova. Volte à senha original do mesmo jeito.
  - Esperado: Senha errada e senhas diferentes mostram erro dentro da janela; a troca vale na hora no painel e no SSH; você continua logado. (O script vai pedir a senha nova quando precisar.)

- [ ] **15. Trocar senha derrubando outros aparelhos** (`geral-senha-outros`, qualquer)
  - Fazer: Entre no painel também pelo celular. No PC, troque a senha marcando “Encerrar as sessões do painel em outros aparelhos”. Recarregue no celular.
  - Esperado: No celular o painel pede login de novo; no PC você continua logado.

- [ ] **16. Trocar nome de usuário** (`geral-usuario`, qualquer)
  - Fazer: Em Geral › Conta e senha › Trocar nome de usuário, teste um nome inválido (ex.: “Root”) e nomes diferentes nas duas caixas; depois troque de verdade. Entre no SSH com o nome novo. Volte ao nome original.
  - Esperado: Erros claros; a troca derruba só as sessões SSH; o painel continua aberto; o SSH aceita o nome novo e recusa o antigo.

- [ ] **17. Backup e restauração** (`geral-backup`, qualquer)
  - Fazer: Em Geral › Nome, backup e reset: baixe o backup, mude algo simples (ex.: nome do hotspot) e restaure o backup.
  - Esperado: O arquivo baixa; a restauração volta a configuração anterior.

- [ ] **18. Reiniciar pelo painel** (`geral-reiniciar`, qualquer)
  - Fazer: Em Geral, toque em Reiniciar e confirme. Espere voltar e abra o painel.
  - Esperado: O dongle volta em 1–2 minutos com tudo funcionando (Wi-Fi, painel, internet).

## Internet

- [ ] **19. Renomear o hotspot** (`net-hotspot`, qualquer)
  - Fazer: Em Internet › Wi-Fi e hotspot, troque nome e senha do hotspot. Conecte o celular na rede nova.
  - Esperado: A rede some e volta com o nome novo; o celular conecta com a senha nova e navega (se houver internet).

- [ ] **20. Aparelhos conectados e IP fixo** (`net-dhcp`, qualquer)
  - Fazer: Em Internet › LAN, DHCP e IP fixo, veja o celular na lista, fixe um IP pra ele, desconecte e reconecte o Wi-Fi do celular.
  - Esperado: O celular aparece na lista e recebe o IP fixado ao reconectar.

- [ ] **21. Mudança de rede com reversão automática** (`net-rollback`, USB)
  - Fazer: Em LAN, DHCP e IP fixo, mude o IP do dongle (ex.: 192.168.101.1), salve e NÃO confirme. Espere 3 minutos.
  - Esperado: O acesso cai; em até 3 minutos o dongle volta sozinho ao IP anterior e o painel abre em 192.168.100.1.

- [ ] **22. Mudança de rede confirmada** (`net-rollback-confirmar`, USB)
  - Fazer: Repita a mudança de IP, reconecte (desplugue/plugue o USB se preciso), abra o endereço novo e confirme. Depois volte ao IP original do mesmo jeito.
  - Esperado: Com a confirmação a mudança fica; o painel responde no IP novo; a volta ao IP original também funciona.

- [ ] **23. Firewall e redirecionamento de porta** (`net-firewall`, qualquer)
  - Fazer: Em Internet › Firewall e portas, adicione um redirecionamento qualquer e remova em seguida.
  - Esperado: Adiciona e remove sem erro; a internet dos aparelhos continua funcionando.

- [ ] **24. Conectar o dongle no Wi-Fi de casa** (`net-wifi-cliente`, tomada)
  - Fazer: Com o dongle na tomada, conecte o dongle a uma rede Wi-Fi em Internet › Conectar a uma rede Wi-Fi. ANOTE o endereço que a tela mostrar ao conectar. Entre na mesma rede com o celular/PC e abra esse endereço (ou opendongle.local, ou ferramentas/opendongle_localizar.py).
  - Esperado: A tela informa o endereço recebido do roteador; o hotspot some, o LED fica azul e o painel abre nesse endereço pela rede de casa.

- [ ] **25. Resgate: religar devolve o hotspot** (`net-resgate-boot`, tomada)
  - Fazer: Com o dongle conectado no Wi-Fi de casa, tire da tomada, espere 5 segundos e ligue de novo. Espere cerca de 1 minuto e procure a rede do dongle no celular.
  - Esperado: A rede Wi-Fi do dongle volta sozinha (todo boot começa no hotspot). No painel, em Conectar a uma rede Wi-Fi, o botão Reconectar devolve a rede de casa sem pedir a senha.

- [ ] **26. Voltar ao hotspot** (`net-voltar-hotspot`, tomada)
  - Fazer: Pelo painel na rede de casa, em Wi-Fi e hotspot toque em Virar hotspot. Conecte o celular no hotspot.
  - Esperado: O hotspot volta, o LED fica verde e o celular navega.

- [ ] **27. Internet pelo chip 4G** (`net-4g`, tomada)
  - Fazer: Com um chip com dados, ligue o dongle na tomada. Conecte o celular no hotspot e navegue. Abra Internet › Modem 4G e chip.
  - Esperado: Navega pelo 4G; a página do modem mostra operadora e sinal; Reconectar 4G volta a conectar.

- [ ] **28. Navegação via Tor** (`net-tor`, qualquer)
  - Fazer: Em Internet › Navegação via Tor, ligue (na 1ª vez instala), acompanhe até terminar e abra check.torproject.org no celular conectado ao dongle. Depois desligue.
  - Esperado: A instalação termina sozinha; o site confirma que está usando Tor; ao desligar a navegação volta ao normal.

## Acesso remoto

- [ ] **29. Ligar o Tailscale** (`remoto-tailscale`, qualquer)
  - Fazer: Em Acesso remoto, ligue (na 1ª vez instala), use o link de login, entre na sua conta e, de outro aparelho na conta Tailscale, abra http://IP-do-tailscale.
  - Esperado: Status “conectado” com nome e IP; o painel abre pelo IP do Tailscale.

- [ ] **30. Tailscale: LAN e saída de internet** (`remoto-opcoes`, qualquer)
  - Fazer: Marque as opções de LAN e exit node, salve, aprove no admin do Tailscale e teste de outro aparelho.
  - Esperado: Com aprovação, o aparelho remoto alcança a LAN do dongle e/ou sai pela internet dele.

- [ ] **31. Desligar o Tailscale** (`remoto-desligar`, qualquer)
  - Fazer: Toque em Sair da conta e depois em Desligar acesso remoto.
  - Esperado: Status “desligado”; a memória usada volta a cair (Opções avançadas › Memória por serviço).

- [ ] **32. Sessões abertas** (`remoto-sessoes`, USB)
  - Fazer: Abra um SSH no PC (ssh usuario@192.168.100.1) e veja Acesso remoto › Sessões abertas. Toque em Encerrar nessa sessão.
  - Esperado: A sessão aparece com a origem; ao encerrar, o SSH cai na hora e some da lista.

## Bluetooth

- [ ] **33. Ligar Bluetooth e ficar visível** (`bt-ligar`, qualquer)
  - Fazer: Em Dispositivos › Bluetooth, ligue, toque em Ficar visível e procure o dongle no celular.
  - Esperado: O celular encontra o dongle pelo nome dele; ao Ocultar, some da busca.

- [ ] **34. Parear um fone ou caixa** (`bt-parear`, qualquer)
  - Fazer: Coloque o fone em modo de pareamento, toque em Procurar aparelhos e depois em Parear no fone. Responda se aparecer código.
  - Esperado: O fone aparece na busca com nome; o pareamento conclui e ele fica na lista de pareados.

- [ ] **35. Som no fone Bluetooth** (`bt-audio`, qualquer)
  - Fazer: Em Áudio, toque em Ligar áudio Bluetooth (na 1ª vez instala e leva minutos). Conecte o fone em Bluetooth e use o teste de som em Áudio.
  - Esperado: A instalação termina; o fone aparece como saída e toca o som de teste.

- [ ] **36. Fone depois de reiniciar** (`bt-reconectar`, qualquer)
  - Fazer: Reinicie o dongle com o fone pareado. Depois toque em Conectar no fone.
  - Esperado: O fone continua pareado e conecta de novo sem parear outra vez.

- [ ] **37. Desconectar e esquecer** (`bt-esquecer`, qualquer)
  - Fazer: Toque em Desconectar e depois em Esquecer. Desligue o áudio Bluetooth em Áudio.
  - Esperado: O fone sai da lista; o áudio Bluetooth desliga e a memória volta a cair.

## Dispositivos

- [ ] **38. Aparelho USB (pendrive ou placa de som)** (`usb-aparelho`, tomada)
  - Fazer: Com o dongle na tomada e um adaptador OTG, plugue um pendrive ou placa de som. Abra Dispositivos › Aparelhos USB.
  - Esperado: O aparelho aparece na lista; a placa de som aparece em Áudio com volume e teste.

## Áudio

- [ ] **39. Placa de som USB** (`audio-placa`, tomada)
  - Fazer: Com uma placa de som USB, ajuste volume, mudo e use o teste de som e de microfone.
  - Esperado: O volume muda de verdade; o teste toca; o teste de microfone diz se está captando.

## Dispositivos

- [ ] **40. Significado das luzes** (`leds`, tomada)
  - Fazer: Observe os LEDs: hotspot com e sem internet, cliente Wi-Fi, e no PC (USB). Compare com Ajuda › luzes.
  - Esperado: Verde fixo/piscando no hotspot, azul fixo/piscando no cliente, tudo apagado no PC.

## Primeiro uso

- [ ] **41. Cadastro aparece com a senha de fábrica** (`cadastro-aparece`, tomada)
  - Fazer: Antes: rode `teste_campo.py senha-fabrica` com o dongle no PC (volta a senha pra 1). Ligue na tomada, conecte o celular no hotspot.
  - Esperado: O celular abre sozinho (ou ao abrir qualquer site) a tela “Bem-vindo ao seu OpenDongle”; qualquer página do painel leva a ela.

- [ ] **42. Erros do cadastro** (`cadastro-erros`, tomada)
  - Fazer: Teste: senha do root “1”, senhas que não batem, nome com número, usuário “root”, senha do usuário igual à do root. Use Voltar e Continuar.
  - Esperado: Cada erro aparece na etapa certa sem apagar o que já foi digitado; a sugestão de usuário vem do nome.

- [ ] **43. Concluir o cadastro** (`cadastro-concluir`, tomada)
  - Fazer: Preencha tudo certo e conclua. Abra o painel. Em Conta e senha confira usuário e nome.
  - Esperado: “Tudo pronto” com o nome; o painel libera já logado; usuário e nome completo aparecem na conta. (O script vai pedir as credenciais novas.)

- [ ] **44. Cadastro não aparece pelo USB** (`cadastro-usb`, USB)
  - Fazer: Volte a senha pra 1 (`teste_campo.py senha-fabrica`), mantenha o dongle no PC e abra o painel.
  - Esperado: O painel abre normal, sem cadastro.

- [ ] **45. Console serial pede login e recupera senha** (`serial-login`, USB)
  - Fazer: No PC: `sudo screen /dev/ttyACM0 115200`. Tente root com senha errada, depois root com a senha do cadastro e rode `passwd <seu usuário>`.
  - Esperado: Pede login (não entra direto); senha errada é recusada; com a do root entra e a troca de senha do usuário funciona.

## Estabilidade

- [ ] **46. Trocar entre tomada e PC várias vezes** (`est-tomada-pc`, qualquer)
  - Fazer: Alterne 3 vezes: tomada (espere o hotspot) → PC (espere o painel pelo USB) → tomada.
  - Esperado: Cada troca termina no modo certo, sem travar e sem precisar reiniciar.

- [ ] **47. Uso longo** (`est-uso-longo`, tomada)
  - Fazer: Deixe o dongle na tomada com um celular navegando/vendo vídeo por 30 minutos ou mais.
  - Esperado: Sem quedas nem travamentos; o painel continua abrindo no fim.

- [ ] **48. Memória no fim do teste** (`est-memoria`, qualquer)
  - Fazer: Abra Opções avançadas › Memória por serviço.
  - Esperado: RAM disponível confortável; nada desligado continua ocupando memória (Tor, Tailscale, PipeWire).

- [ ] **49. Desligar pelo painel** (`est-desligar`, qualquer)
  - Fazer: Em Geral, toque em Desligar e confirme. Espere 15 s, tire e recoloque.
  - Esperado: Desliga (o painel para de responder) e volta normal ao recolocar.

