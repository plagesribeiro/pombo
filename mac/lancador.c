/* Lançador do serviço no Mac.
 *
 * Fica dentro de "Pombo.app" para o macOS ver o serviço como um app: assim a permissão de acesso aos
 * arquivos (Documentos) é dada uma vez só, para este app, e o python3 e o claude que ele abre herdam essa permissão.
 * Ele só abre o python3 com o script pombo e espera; se o serviço cair, o launchd liga de novo.
 * Sem argumentos e sem terminal, o pombo roda o serviço.
 */
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

#ifndef BOT_PY
#error "compile com -DBOT_PY=\"/caminho/pombo\""
#endif

extern char **environ;

int main(void) {
    char *args[] = {"/usr/bin/python3", BOT_PY, NULL};
    pid_t pid;
    if (posix_spawn(&pid, args[0], NULL, NULL, args, environ) != 0) {
        perror("posix_spawn");
        return 1;
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
