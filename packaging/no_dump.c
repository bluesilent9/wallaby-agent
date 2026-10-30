#define _GNU_SOURCE
#include <sys/prctl.h>
#include <sys/resource.h>
#include <unistd.h>
__attribute__((constructor)) static void protect_memory(void){
 struct rlimit limit={0,0};
 if(setrlimit(RLIMIT_CORE,&limit)||prctl(PR_SET_DUMPABLE,0,0,0,0))_exit(125);
}
