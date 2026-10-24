/* Small native launcher; runtime sources remain installed and auditable. */
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv){
  char **args=calloc((size_t)argc+3,sizeof(char *));
  if(!args)return 1;
  args[0]="/usr/bin/python3";args[1]="/usr/lib/wallaby-agent/src/app.py";
  for(int i=1;i<argc;i++)args[i+1]=argv[i];
  execv(args[0],args);perror("Wallaby Agent");free(args);return 1;
}
