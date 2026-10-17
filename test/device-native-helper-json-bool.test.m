#import <Foundation/Foundation.h>

#include <stdio.h>

typedef int gboolean_equivalent;

int
main(void)
{
  @autoreleasepool {
    for (gboolean_equivalent value = 0; value <= 1; value++) {
      NSDictionary *payload = @{
        @"cleanupIncomplete": value ? @YES : @NO,
      };
      NSError *error = nil;
      NSData *json = [NSJSONSerialization dataWithJSONObject:payload
          options:0 error:&error];
      if (json == nil || fwrite(json.bytes, 1, json.length, stdout) != json.length ||
          fputc('\n', stdout) == EOF)
        return 1;
    }
  }
  return 0;
}
