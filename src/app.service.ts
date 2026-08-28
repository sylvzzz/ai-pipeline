import { Injectable } from "@nestjs/common";

@Injectable()
export class AppService {
  getHello(): string {
    return "Hello everyone!";
  }

  getHealth(): { status: string } {
    return { status: "ok" };
  }
}
