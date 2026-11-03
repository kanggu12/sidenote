TYPE: work
ANSWER: IAM Role 권한, S3 버킷 정책, KMS 권한, VPC 엔드포인트 정책을 순서대로 확인합니다
ASKED: EC2 에서 S3 객체를 읽으려는데 AccessDenied 가 납니다. 어디부터 봐야 하나요?

1. **IAM Role 권한 확인**: 인스턴스에 붙은 역할에 `s3:GetObject` 가 있는지 봅니다.
   `aws sts get-caller-identity` 로 실제로 쓰는 역할부터 확인합니다.

2. **S3 버킷 정책 확인**: 명시적 Deny 가 있으면 Allow 보다 먼저 적용됩니다. 평가 순서는 **명시적 Deny → Allow → 기본 Deny** 입니다.

3. **KMS 키 권한과 객체 암호화 방식을 함께 확인합니다**: 객체가 KMS 로 암호화되어 있으면 키 정책에서 `kms:Decrypt` 도 허용되어야 합니다.

4. **VPC 엔드포인트 정책 확인**: 게이트웨이 엔드포인트를 지나는 경우 그 정책이 버킷을 막고 있을 수 있습니다.

CloudTrail 에서 `AccessDenied` 이벤트의 `errorMessage` 를 보면 어느 단계에서 막혔는지 바로 알 수 있습니다.
